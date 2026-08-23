#!/usr/bin/env python3
# Duet — reasoning-layer golden eval (CI gate: ≥90% of checks must pass).
#
# Runs ASBL-specific scenarios against the live reasoning layer and scores
# intent/objection classification, factual grounding, forbidden-claim canaries,
# brevity, and explicit-evidence qualification signals.
#
# Usage: GEMINI_API_KEY=... python eval/reasoning/run_eval.py

import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from duet_agent import persona  # noqa: E402
from duet_agent.reasoning import Guidance, ReasoningLayer  # noqa: E402
from duet_agent.env import load_repo_env  # noqa: E402

GATE = 0.90
MAX_WORDS = 32


class RequestPacer:
    """Smooth live-eval calls instead of consuming an RPM allowance in a burst."""

    def __init__(self, interval_s: float):
        self.interval_s = max(0.0, interval_s)
        self.next_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self.next_at:
            time.sleep(self.next_at - now)
        self.next_at = time.monotonic() + self.interval_s


def run_scenario(layer: ReasoningLayer, sc: dict, pacer: RequestPacer, retries: int = 1):
    """One live call, with one retry — a transient API blip should not fail CI."""
    for attempt in range(retries + 1):
        pacer.wait()
        layer._call([tuple(h) for h in sc["history"]], sc["user"])
        result = layer.results.get()
        if isinstance(result, Guidance):
            return result
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    return result


def score(sc: dict, g) -> list[tuple[str, bool, str]]:
    if not isinstance(g, Guidance):
        return [("api-call", False, getattr(g, "reason", "no response"))]
    tp = g.talking_point.lower()
    checks = [("intent", g.intent in sc["intent_in"], g.intent)]
    if "objection_in" in sc:
        checks.append(("objection", g.objection_type in sc["objection_in"], str(g.objection_type)))
    for i, group in enumerate(sc.get("mention_groups", [])):
        checks.append((f"grounding-{i}", any(k in tp for k in group), tp[:60]))
    for signal, accepted in sc.get("signals", {}).items():
        actual = g.lead_signals.get(signal)
        checks.append((f"signal-{signal}", actual in accepted, str(actual)))
    if "tools" in sc:
        actual_tools = {action.name for action in g.tool_requests}
        checks.append(("tools", set(sc["tools"]) <= actual_tools, str(sorted(actual_tools))))
    for forbidden in sc.get("forbidden_terms", []):
        checks.append((f"forbid-{forbidden}", forbidden not in tp, tp[:80]))
    checks.append(("capability-truth", persona.response_problem(g.talking_point) is None, tp[:80]))
    checks.append(("fact-ids", all(f in persona.FACT_REGISTRY for f in g.fact_ids), str(g.fact_ids)))
    checks.append(("safe-trace", g.response_strategy in persona.RESPONSE_STRATEGIES, g.response_strategy))
    checks.append(("brevity", len(g.talking_point.split()) <= MAX_WORDS, f"{len(g.talking_point.split())} words"))
    return checks


def main() -> int:
    load_repo_env()
    scenarios = json.loads((Path(__file__).parent / "scenarios.json").read_text())
    layer = ReasoningLayer(timeout_s=20.0)
    interval_s = float(os.environ.get("GEMINI_EVAL_MIN_INTERVAL_SECONDS", "8"))
    pacer = RequestPacer(interval_s)
    print(f"model: {layer.model} · {len(scenarios)} scenarios · {interval_s:g}s request pacing\n")

    passed = total = 0
    for sc in scenarios:
        guidance = run_scenario(layer, sc, pacer)
        checks = score(sc, guidance)
        ok = sum(1 for _, p, _ in checks if p)
        passed += ok
        total += len(checks)
        status = "PASS" if ok == len(checks) else "FAIL"
        print(f"[{status}] {sc['id']:24s} {ok}/{len(checks)}")
        for name, p, detail in checks:
            if not p:
                print(f"        ✗ {name}: {detail}")

    lat = layer.stats.latencies_ms
    accuracy = passed / total if total else 0.0
    print(f"\nchecks: {passed}/{total} = {accuracy:.1%} (gate {GATE:.0%})")
    if lat:
        print(f"latency: avg {statistics.mean(lat):.0f} ms · p95 {sorted(lat)[int(len(lat) * 0.95) - 1]:.0f} ms")
    print(
        f"tokens: {layer.stats.tokens_in} in / {layer.stats.tokens_out} out"
        f" ≈ ${layer.stats.cost_usd(layer.model):.5f} at list price"
    )
    return 0 if accuracy >= GATE else 1


if __name__ == "__main__":
    raise SystemExit(main())
