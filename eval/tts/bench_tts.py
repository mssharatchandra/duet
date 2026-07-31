#!/usr/bin/env python3
# Duet — TTS benchmark. Measures the metric that decides conversational feel.
#
# TTFB (time to FIRST audio chunk) is the number that matters. Total synthesis
# time (RTF) matters only for cost. In a conversation nobody experiences your
# throughput; they experience the silence before you start speaking. A backend
# with worse RTF but better TTFB is the better voice for a live agent.
#
# Usage: agent/.venv/bin/python -u eval/tts/bench_tts.py [--backends piper,kokoro]

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

from duet_agent import tts  # noqa: E402

SCENARIOS = ROOT / "eval" / "bench" / "scenarios.json"
OUT = Path(__file__).parent


def utterances(limit: int = 0) -> list[str]:
    texts = [t["text"] for sc in json.loads(SCENARIOS.read_text()) for t in sc["turns"]]
    return texts[:limit] if limit else texts


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9  # bytes on macOS


def bench(name: str, texts: list[str]) -> dict:
    print(f"\n[{name}] loading …", flush=True)
    t0 = time.perf_counter()
    try:
        voice = tts.load(name)
    except Exception as e:
        print(f"[{name}] UNAVAILABLE: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return {"backend": name, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    load_s = time.perf_counter() - t0
    print(f"[{name}] loaded in {load_s:.1f}s", flush=True)

    ttfb_ms: list[float] = []
    rtfs: list[float] = []
    first_audio: np.ndarray | None = None

    for i, text in enumerate(texts, 1):
        t0 = time.perf_counter()
        chunks: list[np.ndarray] = []
        ttfb = None
        try:
            for chunk in voice.synthesize_stream(text):
                if ttfb is None:
                    ttfb = (time.perf_counter() - t0) * 1e3  # first audible byte
                chunks.append(chunk)
        except Exception as e:
            print(f"[{name}] synth failed on utterance {i}: {type(e).__name__}: {str(e)[:80]}", flush=True)
            continue
        total_s = time.perf_counter() - t0
        if not chunks or ttfb is None:
            continue
        pcm = np.concatenate(chunks)
        audio_s = len(pcm) / tts.PIPELINE_RATE
        ttfb_ms.append(ttfb)
        rtfs.append(total_s / max(audio_s, 1e-9))
        if first_audio is None:
            first_audio = pcm
        if i % 10 == 0:
            print(f"[{name}] {i}/{len(texts)} · ttfb p50 so far {np.percentile(ttfb_ms, 50):.0f} ms", flush=True)

    if not ttfb_ms:
        return {"backend": name, "error": "no utterances synthesized"}
    if first_audio is not None:
        tts.write_wav(OUT / "samples" / f"{name}.wav", first_audio)

    return {
        "backend": name,
        "load_s": round(load_s, 1),
        "ttfb_p50_ms": round(float(np.percentile(ttfb_ms, 50)), 1),
        "ttfb_p95_ms": round(float(np.percentile(ttfb_ms, 95)), 1),
        "rtf_mean": round(float(np.mean(rtfs)), 3),
        "peak_rss_gb": round(peak_rss_gb(), 2),
        "utterances": len(ttfb_ms),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", default=",".join(tts.available_backends()))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    texts = utterances(args.limit)
    print(f"benchmarking {args.backends} over {len(texts)} utterances")
    results = [bench(name.strip(), texts) for name in args.backends.split(",")]

    print(f"\n{'backend':14s} {'TTFB p50':>10s} {'TTFB p95':>10s} {'RTF':>7s} {'load':>7s}")
    print("-" * 54)
    for r in results:
        if "error" in r:
            print(f"{r['backend']:14s} {'— ' + r['error'][:36]:>36s}")
            continue
        print(f"{r['backend']:14s} {r['ttfb_p50_ms']:9.0f}ms {r['ttfb_p95_ms']:9.0f}ms "
              f"{r['rtf_mean']:6.2f}x {r['load_s']:6.1f}s")

    ok = [r for r in results if "error" not in r]
    if ok:
        best = min(ok, key=lambda r: r["ttfb_p50_ms"])
        print(f"\nlowest TTFB: {best['backend']} at {best['ttfb_p50_ms']:.0f} ms p50")
        print("Reminder: TTFB decides conversational feel; voice QUALITY is a human")
        print(f"judgment this harness does not measure — listen to {OUT.name}/samples/*.wav.")
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {(OUT / 'results.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
