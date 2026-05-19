"""Agent-driven WebSocket scenario tests (real Gemini in the loop)."""

from __future__ import annotations

import asyncio
import json

import websockets

from .common import BACKEND_URL, Report

SCENARIOS = [
    {
        "name": "cold_start_plan",
        "uid_prefix": "scen_a",
        "prompts": ["Plan my day for LoRa IoT and edge inference."],
        "must_call": ["build_or_revise_plan"],
        "must_not_say": ["i can't", "i apologize"],
    },
    {
        "name": "locate_explicit_booth",
        "uid_prefix": "scen_b",
        "prompts": ["I'm at booth 272. What's nearby for LoRa IoT?"],
        "must_call": ["set_user_location", "query_nearby"],
        "tool_order": ["set_user_location", "query_nearby"],
    },
    {
        "name": "locate_by_company",
        "uid_prefix": "scen_c",
        "prompts": ["I'm at SAP. What's near me?"],
        "must_call": ["set_user_location", "query_nearby"],
        "tool_order": ["set_user_location", "query_nearby"],
    },
    {
        "name": "discover_similar",
        "uid_prefix": "scen_d",
        "prompts": ["I just talked to Deloitte. Who's similar?"],
        # Either path is acceptable: semantic search OR locate + query_nearby
        "must_call_any": [["search_entities"], ["set_user_location", "query_nearby"]],
    },
    {
        "name": "time_budget_two_turn",
        "uid_prefix": "scen_e",
        "prompts": [
            "I'm at booth 272.",
            "I have 15 minutes before my next talk. What should I see?",
        ],
        "must_call": ["set_user_location", "query_nearby"],
    },
    {
        "name": "entity_missing",
        "uid_prefix": "scen_f",
        "prompts": ["Tell me about Foo Industries Quantum LLC."],
        "must_call": ["search_entities"],
        "must_say": ["couldn't find", "no match", "don't have", "not in"],
    },
    {
        "name": "recap_empty",
        "uid_prefix": "scen_g",
        "prompts": ["Recap my day so far."],
        "must_call": ["summarize_day"],
    },
    {
        "name": "replan_after_initial",
        "uid_prefix": "scen_h",
        "prompts": [
            "Plan my day for cybersecurity.",
            "Drop the 2pm session and find something on AI agents instead.",
        ],
        "must_call": ["build_or_revise_plan"],
    },
    {
        "name": "contradicting_interests",
        "uid_prefix": "scen_i",
        "prompts": [
            "Plan my day for LoRa IoT.",
            "Actually I'm more interested in LLM evaluation, what's good this afternoon?",
        ],
        # Either: full re-plan, or a search of new topic
        "must_call_any": [["build_or_revise_plan"], ["search_entities"]],
    },
    {
        "name": "location_then_recap",
        "uid_prefix": "scen_j",
        "prompts": [
            "I'm at booth 269.",
            "Recap my day.",
        ],
        "must_call": ["set_user_location", "summarize_day"],
    },
    {
        "name": "greeting_short",
        "uid_prefix": "scen_k",
        "prompts": ["Hi"],
        "must_call": [],  # no tools required for a greeting
        "max_chars": 600,
    },
    {
        "name": "show_on_map",
        "uid_prefix": "scen_l",
        "prompts": ["Show me cooling and data center booths on the map."],
        "must_call": ["search_entities"],
    },
]


async def run_scenario(scen):
    import time
    uid = f"{scen['uid_prefix']}_{int(time.time())}"
    uri = BACKEND_URL.replace("http://", "ws://") + f"/ws/chat/{uid}"
    tools_called: list[str] = []
    final_text = ""
    async with websockets.connect(uri, max_size=2**22) as ws:
        for prompt in scen["prompts"]:
            await ws.send(json.dumps({"text": prompt}))
            this_text = ""
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=70)
                except asyncio.TimeoutError:
                    return tools_called, final_text + "[TIMEOUT]"
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "tool_call":
                    tools_called.append(msg["name"])
                elif t == "text_delta":
                    this_text += msg.get("delta", "")
                elif t == "done":
                    break
                elif t == "error":
                    return tools_called, this_text + f"[ERROR:{msg.get('message')}]"
            final_text = this_text
    return tools_called, final_text


def run() -> Report:
    r = Report("chat scenarios (live Gemini)")
    for scen in SCENARIOS:
        try:
            tools, text = asyncio.run(run_scenario(scen))
        except Exception as e:
            r.fail(f"{scen['name']} exception", str(e)[:200])
            continue

        # Assertions
        scen_passed = True
        for must in scen.get("must_call", []):
            if must not in tools:
                r.fail(f"{scen['name']}: tool '{must}' not called", f"tools={tools}, text={text[:140]!r}")
                scen_passed = False
        # must_call_any: a list of acceptable tool-set alternatives; pass if any
        # alternative is satisfied (every tool in that alternative was called).
        for alts in scen.get("must_call_any", []):
            pass  # handled below as a group
        any_groups = scen.get("must_call_any")
        if any_groups:
            satisfied = any(all(t in tools for t in alt) for alt in any_groups)
            if not satisfied:
                r.fail(f"{scen['name']}: no acceptable tool combination called",
                       f"tried {any_groups}, got {tools}")
                scen_passed = False
        order = scen.get("tool_order")
        if order:
            idxs = [tools.index(n) if n in tools else -1 for n in order]
            if any(i < 0 for i in idxs) or idxs != sorted(idxs):
                r.fail(f"{scen['name']}: tool order wrong", f"expected {order}, got {tools}")
                scen_passed = False
        lc = text.lower()
        for ns in scen.get("must_not_say", []):
            if ns.lower() in lc:
                r.fail(f"{scen['name']}: said {ns!r}", text[:160])
                scen_passed = False
        ms = scen.get("must_say")
        if ms and not any(s.lower() in lc for s in ms):
            r.fail(f"{scen['name']}: missing expected phrase", f"expected one of {ms}, got {text[:160]!r}")
            scen_passed = False
        max_c = scen.get("max_chars")
        if max_c and len(text) > max_c:
            r.fail(f"{scen['name']}: response too long ({len(text)}>{max_c})")
            scen_passed = False
        if not text.strip():
            r.fail(f"{scen['name']}: empty response")
            scen_passed = False
        if scen_passed:
            r.ok(f"{scen['name']} ({len(tools)} tools, {len(text)} chars)")
    return r


if __name__ == "__main__":
    run().print_summary()
