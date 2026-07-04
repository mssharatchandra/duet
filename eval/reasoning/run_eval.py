#!/usr/bin/env python3
# Duet — reasoning-layer golden eval (CI gate: ≥90% of checks must pass).
#
# Runs the 12 scenarios in scenarios.json against the live reasoning layer and
# scores structured checks: intent classification, objection classification,
# grounding (must mention facts from the sheet — including two hallucination
# canaries that must DECLINE features Brewline doesn't have), brevity, and
# lead-signal tracking. Stdlib only, so CI needs nothing but Python 3.12.
#
# Usage: GEMINI_API_KEY=... python eval/reasoning/run_eval.py

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from duet_agent.reasoning import Guidance, ReasoningLayer  # noqa: E402

GATE = 0.90
MAX_WORDS = 30  # prompt asks ≤22; slack for connectives so the gate tests substance, not luck


def run_scenario(layer: ReasoningLayer, sc: dict, retries: int = 1):
    """One live call, with one retry — a transient API blip should not fail CI."""
    for attempt in range(retries + 1):
        layer._call([tuple(h) for h in sc["history"]], sc["user"])
        result = layer.results.get()
        if isinstance(result, Guidance):
            return result
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
    if "timeline_in" in sc:
        checks.append(("signal-timeline", g.lead_signals["timeline"] in sc["timeline_in"], g.lead_signals["timeline"]))
    if "authority_in" in sc:
        checks.append(("signal-authority", g.lead_signals["authority"] in sc["authority_in"], g.lead_signals["authority"]))
    checks.append(("brevity", len(g.talking_point.split()) <= MAX_WORDS, f"{len(g.talking_point.split())} words"))
    return checks


def main() -> int:
    scenarios = json.loads((Path(__file__).parent / "scenarios.json").read_text())
    layer = ReasoningLayer(timeout_s=20.0)
    print(f"model: {layer.model} · {len(scenarios)} scenarios\n")

    passed = total = 0
    for sc in scenarios:
        guidance = run_scenario(layer, sc)
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
