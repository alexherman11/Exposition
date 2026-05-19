"""The conversational agent (§4).

Two-model architecture (§4.1):
  - Gemini 2.5 Flash — chat front, tool dispatch, streaming.
  - Gemini 2.5 Pro — invoked via build_or_revise_plan for itinerary work.

We use the google-genai Python SDK with function-calling. Each chat turn
becomes a tool-loop: model produces either text or a function call → we
dispatch → feed back the result → repeat until no more function calls or
we hit a turn cap.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from .store import get_store
from .tools import TOOL_IMPLS, TOOL_SCHEMAS


SYSTEM_PROMPT = """You are the Expo Concierge, an AI agent helping an attendee navigate
TechEx North America 2026 (May 18–19, San Jose McEnery Convention Center).

You operate three coupled views the attendee can see: a chat, a live floorplan
map, and a schedule timeline. When you call tools, the map and schedule
update visually. Use this — highlight things; light up the booths you
mention; add cards to the schedule when you plan.

Grounding rules (§4.2):
  - For ANY named entity (company, speaker, session, booth), call search_entities
    BEFORE answering. If it's not in the corpus, say so plainly and offer web_search.
  - Label provenance briefly: "(from their booth page)", "(from web search)",
    "(general knowledge)". Don't fabricate.
  - When the user says where they are or who they just talked to, call
    set_user_location FIRST and confirm in chat, THEN query_nearby if needed.
  - When the user asks to plan their day, use build_or_revise_plan.
  - Keep responses tight — under ~120 words unless the user asks for detail.
  - Use the user profile context (interests, recent behavior) to weight answers.
  - Be a concierge, not a bot. Warm, brief, direct.

When uncertainty matters, surface it. When you change the map or schedule, say
"I highlighted X" or "I added Y to your schedule" — the visual change is part
of the answer.
"""


@dataclass
class ChatTurn:
    role: str  # "user" | "model" | "tool"
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[dict] = None


@dataclass
class Conversation:
    user_id: str
    turns: list[ChatTurn] = field(default_factory=list)


def _profile_block(user_id: str) -> str:
    p = get_store().get_profile(user_id)
    return (
        "USER PROFILE:\n"
        f"- name: {p.name}\n"
        f"- role: {p.role or 'unspecified'}\n"
        f"- company: {p.company or 'unspecified'}\n"
        f"- stable interests: {', '.join(p.interests) or 'none yet'}\n"
        f"- today's session intent: {', '.join(p.session_intent) or 'unset'}\n"
        f"- declared location: {p.location_reference or 'unset'}\n"
        f"- recent behavior (last 5): {p.behavioral_log[-5:]}\n"
        f"- imported connections: {len(p.connections)}\n"
        f"- today is {date.today().isoformat()}"
    )


def _to_gemini_tools():
    """Convert TOOL_SCHEMAS into google-genai FunctionDeclaration list."""
    from google.genai import types
    return [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
            )
            for t in TOOL_SCHEMAS
        ])
    ]


def _new_client():
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def _to_gemini_history(conv: Conversation):
    """Translate our ChatTurn list into google-genai Content list."""
    from google.genai import types
    contents = []
    for t in conv.turns:
        if t.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=t.text or "")]))
        elif t.role == "model" and t.tool_name:
            contents.append(types.Content(role="model", parts=[types.Part.from_function_call(name=t.tool_name, args=t.tool_args or {})]))
        elif t.role == "model":
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=t.text or "")]))
        elif t.role == "tool":
            contents.append(types.Content(role="user", parts=[types.Part.from_function_response(name=t.tool_name or "", response=t.tool_result or {})]))
    return contents


async def run_turn(conv: Conversation, user_text: str, max_steps: int = 6) -> AsyncGenerator[dict, None]:
    """Run one user turn. Yields a stream of events:
        {"type": "tool_call",   "name": ..., "args": ...}
        {"type": "tool_result", "name": ..., "result": ...}
        {"type": "text_delta",  "delta": ...}
        {"type": "done"}
    """
    from google.genai import types

    client = _new_client()
    conv.turns.append(ChatTurn(role="user", text=user_text))

    system = SYSTEM_PROMPT + "\n\n" + _profile_block(conv.user_id)
    tools = _to_gemini_tools()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        temperature=0.4,
    )

    for step in range(max_steps):
        contents = _to_gemini_history(conv)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=cfg,
        )
        cand = resp.candidates[0] if resp.candidates else None
        if not cand or not cand.content or not cand.content.parts:
            yield {"type": "done"}
            return

        # Walk parts: either text or function_call
        function_calls = []
        full_text = ""
        for part in cand.content.parts:
            if getattr(part, "function_call", None):
                fc = part.function_call
                function_calls.append((fc.name, dict(fc.args or {})))
            elif getattr(part, "text", None):
                full_text += part.text

        if function_calls:
            for name, args in function_calls:
                yield {"type": "tool_call", "name": name, "args": args}
                conv.turns.append(ChatTurn(role="model", tool_name=name, tool_args=args))
                impl = TOOL_IMPLS.get(name)
                if not impl:
                    result = {"error": f"unknown tool {name}"}
                else:
                    try:
                        result = impl(conv.user_id, **args)
                    except TypeError as e:
                        result = {"error": f"bad args: {e}", "args": args}
                    except Exception as e:
                        result = {"error": str(e)}
                yield {"type": "tool_result", "name": name, "result": result}
                conv.turns.append(ChatTurn(role="tool", tool_name=name, tool_result=result))
            continue

        # Otherwise: text turn → final
        if full_text:
            yield {"type": "text_delta", "delta": full_text}
            conv.turns.append(ChatTurn(role="model", text=full_text))
        yield {"type": "done"}
        return

    yield {"type": "done", "warn": "max_steps_reached"}


def reset_conversation(user_id: str) -> Conversation:
    return Conversation(user_id=user_id)
