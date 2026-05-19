/* Top-level orchestrator. Holds shared state and routes view switches. */

import { initChat, sendChat } from "./chat.js";
import { initMap, applyHighlights, setYouAreHere } from "./map.js";
import { initSchedule, refreshSchedule } from "./schedule.js";

const API_BASE = window.location.port === "5173" || window.location.port === "8080"
  ? "http://" + window.location.hostname + ":8000"
  : "";

const WS_BASE = (API_BASE || window.location.origin).replace(/^http/, "ws");

/* All API calls must include credentials so the session cookie travels. */
async function api(path, opts = {}) {
  const url = API_BASE + path;
  const merged = { credentials: "include", ...opts };
  if (merged.body && !(merged.body instanceof FormData) && typeof merged.body !== "string") {
    merged.body = JSON.stringify(merged.body);
    merged.headers = { "Content-Type": "application/json", ...(merged.headers || {}) };
  }
  return fetch(url, merged);
}
export { api };

export const state = {
  userId: null,             // resolved from /api/me
  user: null,               // full user card { name, picture_url, is_guest, ... }
  apiBase: API_BASE,
  wsBase: WS_BASE,
  view: "chat",
  highlights: [],
  plan: [],
  booths: [],
  exhibitors: [],
  sessions: [],
  annotations: {},
  linkedinConfigured: false,
};

/* ─── view switching ─── */
function setView(name) {
  state.view = name;
  document.querySelectorAll(".view-switch button").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view-pane").forEach(p => p.hidden = (p.dataset.pane !== name && p.dataset.pane !== "chat"));
  document.body.classList.toggle("view-map", name === "map");
  document.body.classList.toggle("view-schedule", name === "schedule");
  document.querySelector('.view-pane[data-pane="map"]').hidden = name !== "map";
  document.querySelector('.view-pane[data-pane="schedule"]').hidden = name !== "schedule";
}

/* ─── user pill rendering ─── */
function initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

function renderUserPill() {
  const pill = document.getElementById("user-pill");
  if (!pill || !state.user) return;
  const u = state.user;
  const avatarHtml = u.picture_url
    ? `<img class="avatar" src="${u.picture_url}" alt="" referrerpolicy="no-referrer">`
    : `<div class="avatar">${initials(u.name)}</div>`;
  const subline = u.is_guest
    ? `Guest session ${state.linkedinConfigured ? '· <a href="#" class="signin-link" id="signin-link">Sign in with LinkedIn</a>' : "· local demo"}`
    : `${u.email ? u.email + " · " : ""}<a href="#" class="signin-link" id="signout-link">Sign out</a>`;
  pill.innerHTML = `
    ${avatarHtml}
    <div class="meta">
      <div class="name">${u.name || "Attendee"}</div>
      <div class="interests">${subline}</div>
    </div>
  `;
  const si = document.getElementById("signin-link");
  if (si) si.addEventListener("click", e => { e.preventDefault(); window.location.href = API_BASE + "/api/auth/linkedin/login"; });
  const so = document.getElementById("signout-link");
  if (so) so.addEventListener("click", async e => {
    e.preventDefault();
    await api("/api/auth/logout", { method: "POST" });
    window.location.reload();
  });
}

/* ─── boot ─── */
async function boot() {
  // 1. Resolve who we are (mints a guest cookie on first visit).
  try {
    const me = await api("/api/me").then(r => r.json());
    state.userId = me.user_id;
    state.user = me;
    state.linkedinConfigured = !!me.linkedin_configured;
    renderUserPill();
  } catch (e) {
    console.error("auth bootstrap failed", e);
    toast("Backend not reachable — start it on :8000");
    state.userId = "demo";  // last-ditch fallback so map/schedule still render
  }

  // Show a one-shot toast if we just came back from a failed OAuth callback.
  const params = new URLSearchParams(window.location.search);
  if (params.get("auth_error")) {
    toast("LinkedIn sign-in failed: " + params.get("auth_error"), "error");
    history.replaceState({}, "", window.location.pathname);
  }

  // 2. Fetch corpus
  try {
    const [booths, exhibitors, sessions, speakers, annSummary] = await Promise.all([
      api("/api/booths").then(r => r.json()),
      api("/api/exhibitors").then(r => r.json()),
      api("/api/sessions").then(r => r.json()),
      api("/api/speakers").then(r => r.json()).catch(() => []),
      api("/api/annotations/summary").then(r => r.json()).catch(() => ({})),
    ]);
    state.booths = booths;
    state.exhibitors = exhibitors;
    state.speakers = speakers || [];
    state.sessions = sessions;
    state.annotations = annSummary;
  } catch (e) {
    console.error("corpus fetch failed", e);
    toast("Backend not reachable — start it on :8000");
  }

  initMap(state);
  initSchedule(state);
  initChat(state);

  // 3. Plan
  try {
    state.plan = await api("/api/plan").then(r => r.json());
    refreshSchedule();
  } catch (e) {}

  // 4. UI handlers
  document.querySelectorAll(".view-switch button").forEach(b => {
    b.addEventListener("click", () => setView(b.dataset.view));
  });
  document.querySelectorAll(".chip").forEach(c => {
    c.addEventListener("click", () => sendChat(c.textContent));
  });
  const form = document.getElementById("chat-form");
  form.addEventListener("submit", e => {
    e.preventDefault();
    const input = document.getElementById("chat-text");
    const text = input.value.trim();
    if (text) {
      sendChat(text);
      input.value = "";
    }
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  }
}

export function toast(text, kind="info") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = text;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

export async function handleAgentEvent(ev) {
  if (ev.type === "tool_result" && ev.result && ev.result._ui) {
    const ui = ev.result._ui;
    if (ui.you_are_here) setYouAreHere(ui.you_are_here);
    if (ui.highlights && ui.highlights.length) {
      applyHighlights(ui.highlights, ui.from);
      if (state.view !== "map" && ev.name !== "search_entities") {
        if (ev.name === "query_nearby" || ev.name === "highlight_on_map") setView("map");
      }
    }
    if (ui.plan_changed) {
      state.plan = await api("/api/plan").then(r => r.json());
      refreshSchedule();
      if (ev.name === "build_or_revise_plan") setView("schedule");
    }
    if (ui.annotation_updated) {
      state.annotations = await api("/api/annotations/summary").then(r => r.json());
    }
  }
}

boot();
