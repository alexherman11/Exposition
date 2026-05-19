"""End-to-end smoke test of the chat agent over WebSocket.

Drives the gameplan §5.2 scenarios one at a time as a fresh user. For each
prompt, records what tools were called and the agent's reply, and asserts
the structural expectations (tool ordering, response shape).

Run with the backend live on :8000:
    python scripts/smoke_chat.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

import websockets

SCENARIOS = [
    {
        "name": "cold_start_plan",
        "user_id": "smoke_cold",
        "prompts": ["Plan my day for LoRa IoT and edge inference."],
        "expect_tools": ["build_or_revise_plan"],
    },
    {
        "name": "locate_explicit",
        "user_id": "smoke_locate",
        "prompts": ["I'm at booth 272. What's nearby that's interesting for LoRa IoT?"],
        "expect_tools": ["set_user_location", "query_nearby"],
        "expect_tool_order": ["set_user_location", "query_nearby"],
    },
    {
        "name": "discover_similar",
        "user_id": "smoke_discover",
        "prompts": ["I just talked to Deloitte — who's similar?"],
        "expect_tools": ["set_user_location", "search_entities"],
    },
    {
        "name": "time_budget",
        "user_id": "smoke_budget",
        "prompts": [
            "I'm at booth 272.",
            "I have 15 minutes before my next talk. What should I see?",
        ],
        "expect_tools": ["query_nearby"],
    },
    {
        "name": "entity_missing",
        "user_id": "smoke_missing",
        "prompts": ["Tell me about Foo Industries Quantum LLC."],
        "expect_tools": ["search_entities"],  # agent should search and find nothing, then explain
    },
    {
        "name": "recap",
        "user_id": "smoke_recap",
        "prompts": ["Recap my day so far."],
        "expect_tools": ["summarize_day"],
    },
]


async def run_one(scen):
    uri = f"ws://127.0.0.1:8000/ws/chat/{scen['user_id']}"
    tools_called = []
    final_text = ""
    print(f"\n── {scen['name']} ─────────────────────────────────────────────────")
    async with websockets.connect(uri, max_size=2**22) as ws:
        # reset conv for a clean slate
        await ws.send(json.dumps({"type": "reset"}))
        # consume reset_ack
        await asyncio.wait_for(ws.recv(), timeout=5)
        for prompt in scen["prompts"]:
            print(f"USER: {prompt}")
            await ws.send(json.dumps({"text": prompt}))
            this_text = ""
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    print("  ⚠ timeout waiting for done")
                    break
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "tool_call":
                    tools_called.append(msg.get("name"))
                    print(f"  → tool: {msg.get('name')}({json.dumps(msg.get('args',{}))[:120]})")
                elif t == "tool_result":
                    r = msg.get("result", {})
                    summary = ", ".join(f"{k}={str(v)[:50]}" for k, v in r.items() if k not in ("_ui","results","plan") and not isinstance(v, list))
                    print(f"  ← result[{msg.get('name')}]: {summary[:200]}")
                elif t == "text_delta":
                    this_text += msg.get("delta", "")
                elif t == "done":
                    break
                elif t == "error":
                    print(f"  ✗ error: {msg.get('message')}")
                    break
            final_text = this_text
            print(f"AGENT: {textwrap.shorten(this_text, 280)}")
    # Assertions
    passes = []
    fails = []
    for expect in scen.get("expect_tools", []):
        if expect in tools_called:
            passes.append(f"called {expect}")
        else:
            fails.append(f"MISSING tool: {expect}")
    order = scen.get("expect_tool_order")
    if order:
        idxs = []
        for name in order:
            i = tools_called.index(name) if name in tools_called else -1
            idxs.append(i)
        if all(i >= 0 for i in idxs) and idxs == sorted(idxs):
            passes.append(f"tool order ok: {' < '.join(order)}")
        else:
            fails.append(f"WRONG tool order. expected {order}, got {tools_called}")
    if not final_text.strip():
        fails.append("empty agent response")
    return {"scenario": scen["name"], "tools": tools_called, "passes": passes, "fails": fails, "text_len": len(final_text)}


async def main():
    report = []
    for scen in SCENARIOS:
        try:
            r = await run_one(scen)
        except Exception as e:
            r = {"scenario": scen["name"], "tools": [], "passes": [], "fails": [f"exception: {e}"]}
        report.append(r)
    print("\n══════════ SUMMARY ══════════")
    for r in report:
        status = "PASS" if not r["fails"] else "FAIL"
        print(f"[{status}] {r['scenario']:20s} tools={r['tools']}  fails={r['fails']}")
    fails = sum(1 for r in report if r["fails"])
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
