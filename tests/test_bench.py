"""Scenario test bench (§5).

Runs each YAML scenario against the real agent stack. Per-turn assertions
on the agent's response and tool-call trace. LLM-as-judge for response
quality (via Gemini 2.5 Pro). Emits a structured JSON report that the
coding agent can read.

Usage:
    python tests/test_bench.py                   # all scenarios, 1 run each
    python tests/test_bench.py --runs 5          # multiple runs per scenario
    python tests/test_bench.py --scenario cold_start
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # noqa: E402

from app.agent import Conversation, run_turn  # noqa: E402
from app.ingest.embed import build_index  # noqa: E402
from app.store import get_store  # noqa: E402

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def ensure_corpus():
    store = get_store()
    if not store.sessions:
        if not (ROOT / "backend" / "app" / "data" / "embeddings.npy").exists():
            build_index()
        store.load()


def load_scenarios(filter_name: str | None) -> list[dict]:
    out = []
    for p in SCENARIOS_DIR.glob("*.yaml"):
        data = yaml.safe_load(p.read_text())
        if filter_name and data.get("name") != filter_name:
            continue
        out.append(data)
    return out


async def run_scenario(scenario: dict) -> dict:
    """Execute one scenario, capture trace, evaluate assertions."""
    user_id = f"bench_{scenario['name']}_{int(time.time()*1000)}"
    store = get_store()
    profile = scenario.get("initial_profile", {})
    if profile:
        store.update_profile(user_id, **profile)

    conv = Conversation(user_id=user_id)
    turn_results = []
    for turn in scenario.get("turns", []):
        text = turn["user"]
        trace = {"user": text, "events": []}
        async for ev in run_turn(conv, text, max_steps=6):
            trace["events"].append(ev)
        # collect response text
        response = ""
        tools = []
        for ev in trace["events"]:
            if ev.get("type") == "text_delta":
                response += ev.get("delta", "")
            elif ev.get("type") == "tool_call":
                tools.append({"name": ev["name"], "args": ev.get("args", {})})
            elif ev.get("type") == "tool_result":
                pass
        trace["response"] = response
        trace["tools"] = tools
        # evaluate assertions
        assertions = turn.get("assertions", []) or []
        passed = []
        failed = []
        for a in assertions:
            key, val = next(iter(a.items()))
            ok, msg = evaluate_assertion(key, val, response, tools)
            (passed if ok else failed).append({"assertion": key, "value": val, "msg": msg})
        trace["assertions"] = {"passed": passed, "failed": failed}
        # rubric / LLM-judge
        rubric = turn.get("rubric")
        if rubric and os.getenv("GEMINI_API_KEY"):
            trace["judge"] = await llm_judge(rubric, text, response, tools)
        turn_results.append(trace)

    return {
        "name": scenario["name"],
        "description": scenario.get("description", ""),
        "turns": turn_results,
    }


def evaluate_assertion(key, val, response, tools):
    tool_names = [t["name"] for t in tools]
    if key == "tool_called":
        return (val in tool_names, f"expected {val} in {tool_names}")
    if key == "tool_called_in_order":
        # val is a list — check that all appear in order in tool_names
        idx = 0
        for needed in val:
            found = False
            while idx < len(tool_names):
                if tool_names[idx] == needed:
                    found = True
                    idx += 1
                    break
                idx += 1
            if not found:
                return (False, f"expected order {val} but trace was {tool_names}")
        return (True, "ok")
    if key == "response_mentions_any":
        for term in val:
            if term.lower() in (response or "").lower():
                return (True, f"found '{term}'")
        return (False, f"none of {val} in response")
    if key == "tool_call_count_max":
        for name, limit in val.items():
            n = tool_names.count(name)
            if n > limit:
                return (False, f"{name} called {n} > {limit}")
        return (True, "ok")
    if key == "web_search_call_count_max":
        n = tool_names.count("web_search")
        return (n <= val, f"web_search called {n} (max {val})")
    if key == "response_max_tokens":
        # rough char→token: 4 chars/token
        approx = len(response) / 4
        return (approx <= val, f"~{approx:.0f} tokens (max {val})")
    if key == "no_fabricated_company":
        # If we mentioned the fake name as if it were real, fail.
        text = response.lower()
        bad = val.lower()
        if bad not in text:
            return (True, "name not present")
        # mention is OK if followed by negative phrasing
        if any(neg in text for neg in ["not in", "don't see", "couldn't find", "no record", "not finding"]):
            return (True, "mentioned with negation")
        return (False, "company mentioned without negation")
    return (False, f"unknown assertion {key}")


async def llm_judge(rubric, user_text, response, tools):
    """Score 1-5 via Gemini 2.5 Pro."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""You are evaluating an AI concierge's response on the following rubric:

{rubric}

USER MESSAGE:
{user_text}

AGENT RESPONSE:
{response}

TOOL CALLS:
{json.dumps(tools, indent=2)}

Return JSON: {{"score": <integer 1-5>, "rationale": "<one sentence>"}}.
"""
    try:
        r = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return json.loads(r.text)
    except Exception as e:
        return {"score": 0, "error": str(e)}


def summarize(report: list[dict]) -> dict:
    total = 0
    passed = 0
    failed_list = []
    judge_scores = []
    for sc in report:
        for t in sc["turns"]:
            ap = t["assertions"]
            total += len(ap["passed"]) + len(ap["failed"])
            passed += len(ap["passed"])
            for f in ap["failed"]:
                failed_list.append({"scenario": sc["name"], **f})
            if "judge" in t and isinstance(t["judge"].get("score"), int):
                judge_scores.append(t["judge"]["score"])
    return {
        "scenarios": len(report),
        "assertions_total": total,
        "assertions_passed": passed,
        "assertions_failed": total - passed,
        "judge_mean": round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None,
        "failed": failed_list[:20],
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", default="tests/bench_report.json")
    args = ap.parse_args()

    ensure_corpus()
    scenarios = load_scenarios(args.scenario)
    print(f"[bench] {len(scenarios)} scenario(s), {args.runs} run(s) each")

    all_reports = []
    for sc in scenarios:
        for r in range(args.runs):
            print(f"  → {sc['name']} run {r+1}/{args.runs}")
            try:
                rep = await run_scenario(sc)
                all_reports.append(rep)
            except Exception as e:
                print(f"    error: {e}")
                all_reports.append({"name": sc["name"], "error": str(e)})

    summary = summarize(all_reports)
    full = {"summary": summary, "details": all_reports}
    Path(args.out).write_text(json.dumps(full, indent=2))
    print()
    print("=" * 56)
    print(f"  Scenarios: {summary['scenarios']}")
    print(f"  Assertions: {summary['assertions_passed']}/{summary['assertions_total']}")
    if summary["judge_mean"]:
        print(f"  Judge mean: {summary['judge_mean']}/5")
    if summary["failed"]:
        print()
        print("  Failed:")
        for f in summary["failed"][:6]:
            print(f"    - [{f['scenario']}] {f['assertion']}: {f['msg']}")
    print("=" * 56)
    print(f"Report: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
