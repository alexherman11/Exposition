"""LinkedIn "Sign In with LinkedIn using OpenID Connect" + session cookies.

Flow:
  GET  /api/auth/linkedin/login    -> 302 to linkedin authorize URL
  GET  /api/auth/linkedin/callback -> exchange code -> userinfo -> upsert
                                       user -> set session cookie -> 302 home
  POST /api/auth/logout            -> clear cookie
  GET  /api/me                     -> { user_id, name, picture_url, ... }

Sessions are signed cookies (itsdangerous), not server-side rows. The cookie
payload is just {"uid": "<user_id>"}. For guest mode we mint a "guest:<uuid>"
id on first request and persist it so plan/annotations survive a reload.

Why a cookie and not a JWT? It's all one origin (the FastAPI app serves the
frontend), so a signed HTTP-only cookie is simpler and immune to XSS-leak of
the token. WebSocket auth just reads the same cookie.

Env vars required for real sign-in (otherwise only guest mode works):
  LINKEDIN_CLIENT_ID
  LINKEDIN_CLIENT_SECRET
  LINKEDIN_REDIRECT_URI   e.g. https://yourapp.up.railway.app/api/auth/linkedin/callback
  SESSION_SECRET          any long random string
"""

from __future__ import annotations

import os
import secrets
import uuid
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from .store import get_store

# ─── config ──────────────────────────────────────────────────────────────

LINKEDIN_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_SCOPES = "openid profile email"

SESSION_COOKIE = "expo_session"
OAUTH_STATE_COOKIE = "expo_oauth_state"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _get_secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        # Dev fallback: stable per-process but reset on restart so dev sessions
        # don't carry across reboots. In prod, *always* set SESSION_SECRET.
        secret = "dev-only-secret-do-not-use-in-prod"
    return secret


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(_get_secret(), salt="expo-session")


def _is_https_request(req: Request) -> bool:
    # Honor X-Forwarded-Proto (Railway terminates TLS at the edge).
    proto = req.headers.get("x-forwarded-proto", req.url.scheme)
    return proto == "https"


def _set_session_cookie(response: Response, user_id: str, secure: bool) -> None:
    token = _serializer().dumps({"uid": user_id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _read_session_cookie(request: Request) -> Optional[str]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
        uid = data.get("uid") if isinstance(data, dict) else None
        return uid
    except BadSignature:
        return None


def linkedin_configured() -> bool:
    return all(os.environ.get(k) for k in ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI"))


# ─── public helpers used by the rest of the app ─────────────────────────

def get_or_create_user_id(request: Request, response: Optional[Response] = None) -> str:
    """Resolve the current user from the session cookie.
    Mints a guest user if none exists. If a Response is supplied, sets the
    cookie when a new guest is minted so the same id sticks across requests.
    """
    uid = _read_session_cookie(request)
    if uid:
        return uid
    guest_id = f"guest:{uuid.uuid4().hex[:16]}"
    # Touch the DB so the user row exists for FK relationships.
    get_store().get_profile(guest_id)
    if response is not None:
        _set_session_cookie(response, guest_id, secure=_is_https_request(request))
    return guest_id


# ─── routes ──────────────────────────────────────────────────────────────

router = APIRouter()


@router.get("/api/auth/linkedin/login")
async def linkedin_login(request: Request):
    if not linkedin_configured():
        raise HTTPException(503, "LinkedIn sign-in is not configured on this server.")
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": os.environ["LINKEDIN_CLIENT_ID"],
        "redirect_uri": os.environ["LINKEDIN_REDIRECT_URI"],
        "scope": LINKEDIN_SCOPES,
        "state": state,
    }
    url = f"{LINKEDIN_AUTHORIZE_URL}?{urlencode(params)}"
    resp = RedirectResponse(url, status_code=302)
    # Stash the state in a short-lived signed cookie so we can verify on callback.
    state_token = _serializer().dumps({"state": state})
    resp.set_cookie(
        OAUTH_STATE_COOKIE,
        state_token,
        max_age=600,
        httponly=True,
        secure=_is_https_request(request),
        samesite="lax",
        path="/",
    )
    return resp


@router.get("/api/auth/linkedin/callback")
async def linkedin_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None):
    if error:
        return RedirectResponse(f"/?auth_error={error}", status_code=302)
    if not code or not state:
        raise HTTPException(400, "missing code or state")

    # Verify state matches the value we stashed pre-redirect.
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    if not state_cookie:
        raise HTTPException(400, "missing oauth state cookie")
    try:
        expected = _serializer().loads(state_cookie).get("state")
    except BadSignature:
        raise HTTPException(400, "bad oauth state cookie")
    if expected != state:
        raise HTTPException(400, "oauth state mismatch")

    if not linkedin_configured():
        raise HTTPException(503, "LinkedIn sign-in is not configured.")

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": os.environ["LINKEDIN_REDIRECT_URI"],
        "client_id": os.environ["LINKEDIN_CLIENT_ID"],
        "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
    }
    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(
            LINKEDIN_TOKEN_URL,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if tok.status_code != 200:
            raise HTTPException(502, f"LinkedIn token exchange failed: {tok.text}")
        access_token = tok.json().get("access_token")
        if not access_token:
            raise HTTPException(502, "LinkedIn did not return access_token")

        userinfo = await client.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo.status_code != 200:
            raise HTTPException(502, f"LinkedIn userinfo failed: {userinfo.text}")
        info = userinfo.json()

    sub = info.get("sub")
    if not sub:
        raise HTTPException(502, "LinkedIn userinfo missing 'sub'")
    name = info.get("name") or f"{info.get('given_name','')} {info.get('family_name','')}".strip() or "LinkedIn User"
    email = info.get("email")
    picture = info.get("picture")

    user_id = get_store().upsert_linkedin_user(sub=sub, email=email, name=name, picture_url=picture)

    # If the visitor had a guest session with state in it, migrate it to the
    # signed-in user so they don't lose their plan.
    prior_guest = _read_session_cookie(request)
    if prior_guest and prior_guest.startswith("guest:") and prior_guest != user_id:
        _migrate_guest_state(prior_guest, user_id)

    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    _set_session_cookie(resp, user_id, secure=_is_https_request(request))
    return resp


def _migrate_guest_state(guest_id: str, user_id: str) -> None:
    """Best-effort: move plan items and annotations from a guest row to the
    newly signed-in user row, then delete the guest user."""
    from sqlalchemy import update
    from .db import Annotation as DBAnnotation
    from .db import PlanItem as DBPlanItem
    from .db import User as DBUser
    from .db import db_session

    with db_session() as s:
        guest = s.get(DBUser, guest_id)
        if guest is None:
            return
        s.execute(update(DBPlanItem).where(DBPlanItem.user_id == guest_id).values(user_id=user_id))
        s.execute(update(DBAnnotation).where(DBAnnotation.user_id == guest_id).values(user_id=user_id))
        # Carry over a guest's uploaded connections / interests if the user row is empty.
        user = s.get(DBUser, user_id)
        if user is not None:
            if not (user.connections or []) and (guest.connections or []):
                user.connections = guest.connections
            if not (user.interests or []) and (guest.interests or []):
                user.interests = guest.interests
            if not user.location_reference and guest.location_reference:
                user.location_reference = guest.location_reference
        s.delete(guest)


@router.post("/api/auth/logout")
async def logout(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/api/me")
async def me(request: Request):
    resp = JSONResponse({})
    uid = get_or_create_user_id(request, resp)
    card = get_store().get_user_card(uid)
    card["linkedin_configured"] = linkedin_configured()
    # Re-bind the body since get_or_create_user_id may have set a guest cookie.
    new_resp = JSONResponse(card)
    for k, v in resp.headers.items():
        if k.lower() == "set-cookie":
            new_resp.headers.append("set-cookie", v)
    return new_resp
