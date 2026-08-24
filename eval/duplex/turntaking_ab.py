#!/usr/bin/env python3
"""Turn-taking A/B for duplex steering configs, on the July benchmark's own terms.

docs/DUPLEX_STEERING.md measured free-run tokens -- a proxy for "does the model
ramble". This measures the metrics the original claim was made in: takeover
rate, handoff latency, overlap and backchannels, via `turntaking.py`. Without
this, a free-run improvement is an unvalidated proxy win.

Everything that defines the comparison is copied from `eval/bench/run_bench.py`
so results sit beside the July baseline (takeover 0.24, handoff p50 240 ms,
p95 3,248 ms, overlap 0.234, 0.4 backchannels/call): same 10 scenarios, same
Piper lessac caller voice, same RMS_USER/RMS_AGENT energy thresholds, same
CALLER_GAP_S / BARGE_AFTER_S scheduling, same 80 ms grid.

What differs between arms is only the steering config:
  --arms "julyish:q=6,delay=1300"  reproduces July's slow-Gemini-loop behaviour
  --arms "fast:q=1,delay=0"        the local KV-cached brain at natural speed

    python eval/duplex/turntaking_ab.py --arms "julyish:q=6,delay=1300;fast:q=1,delay=0"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

RATE = 24_000
FRAME = 1920
FRAME_S = FRAME / RATE
# Copied verbatim from eval/bench/run_bench.py -- changing any of these breaks
# comparability with the July baseline, which is the entire point of this file.
CALLER_GAP_S = 0.7
BARGE_AFTER_S = 0.5
RMS_USER = 0.010
RMS_AGENT = 0.015

_voice = None


def synth(text: str) -> np.ndarray:
    """Piper lessac -> mono float32 @ 24 kHz. Same voice as the July run."""
    global _voice
    if _voice is None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice
        _voice = PiperVoice.load(
            hf_hub_download("rhasspy/piper-voices", "en/en_US/lessac/medium/en_US-lessac-medium.onnx"),
            hf_hub_download("rhasspy/piper-voices", "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"),
        )
    pcm = np.concatenate([np.frombuffer(c.audio_int16_bytes, np.int16) for c in _voice.synthesize(text)])
    pcm = pcm.astype(np.float32) / 32768.0
    src = _voice.config.sample_rate
    n_out = int(len(pcm) * RATE / src)
    return np.interp(np.linspace(0, len(pcm) - 1, n_out), np.arange(len(pcm)), pcm).astype(np.float32)


def frames_of(pcm: np.ndarray) -> list[np.ndarray]:
    n = (len(pcm) + FRAME - 1) // FRAME
    return [np.pad(pcm[i * FRAME:(i + 1) * FRAME],
                   (0, max(0, FRAME - len(pcm[i * FRAME:(i + 1) * FRAME]))))
            for i in range(n)]


def build_stack(temp: float):
    """Load Moshi weights once; hand back a factory for per-call fresh state."""
    import huggingface_hub
    import mlx.core as mx
    import mlx.nn as nn
    import rustymimi
    import sentencepiece
    from moshi_mlx import models, utils

    from duet_agent import local_loop as L

    repo = "kyutai/moshiko-mlx-q4"
    sp = sentencepiece.SentencePieceProcessor(
        huggingface_hub.hf_hub_download(repo, "tokenizer_spm_32k_3.model"))
    model = models.Lm(models.config_v0_1())
    model.set_dtype(mx.bfloat16)
    nn.quantize(model, bits=4, group_size=32)
    model.load_weights(huggingface_hub.hf_hub_download(repo, "model.q4.safetensors"), strict=True)
    model.warmup()
    mimi_file = huggingface_hub.hf_hub_download(repo, "tokenizer-e351c8d8-checkpoint125.safetensors")

    def fresh(hook, steps: int):
        gen = models.LmGen(model=model, max_steps=steps + 10, text_sampler=utils.Sampler(),
                           audio_sampler=utils.Sampler(temp=temp), check=False, on_text_hook=hook)
        return gen, rustymimi.StreamTokenizer(mimi_file)  # type: ignore[attr-defined]

    return L, fresh, sp, mx


def run_call(stack, scenario, brain, quiet_frames: int, steps: int):
    """One duplex call. Mirrors run_bench.duet_call's scheduling and tracking."""
    import mlx.core as mx

    from duet_agent import turntaking
    from duet_agent.injector import TextInjector

    L, fresh, sp, _mx = stack
    holder: dict = {"injector": None}

    def hook(text_tokens):
        injector = holder["injector"]
        if injector is None:
            return
        sampled = int(np.array(text_tokens).reshape(-1)[0])
        forced = injector.hook(sampled)
        if forced != sampled:
            text_tokens[:] = mx.array([[forced]])

    gen, codec = fresh(hook, steps)
    injector = TextInjector(encode=lambda s: sp.encode(s),
                            quiet_frames_to_start=quiet_frames, pace_pads=2)
    holder["injector"] = injector

    turns = list(scenario["turns"])
    turn_frames: list[np.ndarray] = []
    user_active: list[bool] = []
    agent_active: list[bool] = []
    history: list[tuple[str, str]] = []
    silence = np.zeros(FRAME, np.float32)

    agent_run = agent_quiet = 0
    answered = True
    wait_since_turn = 0.0

    for frame in range(steps):
        t = frame * FRAME_S
        if turns and not turn_frames:
            barge = turns[0].get("barge", False)
            due = (
                (frame == 12) if not history else (
                    (agent_run >= round(BARGE_AFTER_S / FRAME_S)) if barge
                    else (answered and agent_quiet >= round(CALLER_GAP_S / FRAME_S))
                )
            )
            if due or (history and t - wait_since_turn > 10.0):
                turn = turns.pop(0)
                turn_frames = frames_of(synth(turn["text"]))
                brain.request(history, turn["text"])
                history.append(("caller", turn["text"]))
                answered = False
                wait_since_turn = t

        result = brain.poll()
        if result is not None and getattr(result, "text", ""):
            injector.inject(result.text)
            history.append(("you", result.text))

        user_frame = turn_frames.pop(0) if turn_frames else silence
        u_rms = float(np.sqrt(np.mean(user_frame ** 2)))
        injector.on_user_frame(u_rms)
        user_active.append(u_rms > RMS_USER)

        codec.encode(np.ascontiguousarray(user_frame, dtype=np.float32))
        deadline = time.time() + 5.0
        while (data := codec.get_encoded()) is None:
            if time.time() > deadline:
                raise RuntimeError("encoder stalled")
            time.sleep(0.001)

        audio_out, _piece = L.step_once(gen, sp, data)
        a_pcm = silence
        if audio_out is not None:
            codec.decode(audio_out)
            got = codec.get_decoded()
            for _ in range(200):
                if got is not None:
                    break
                time.sleep(0.001)
                got = codec.get_decoded()
            if got is not None:
                a_pcm = np.asarray(got, np.float32)[:FRAME]
        a_rms = float(np.sqrt(np.mean(a_pcm ** 2)))
        active = a_rms > RMS_AGENT
        agent_active.append(active)
        agent_run = agent_run + 1 if active else 0
        agent_quiet = agent_quiet + 1 if not active else 0
        if active:
            answered = True

        if not turns and not turn_frames and answered and agent_quiet > round(2.0 / FRAME_S):
            break

    report = turntaking.analyze(user_active, agent_active)
    return report.summary(), {
        "injected": injector.injected,
        "dropped_stale": injector.dropped_stale,
        "cancelled_by_barge_in": injector.cancelled_by_barge_in,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="julyish:q=6,delay=1300;fast:q=1,delay=0")
    parser.add_argument("--scenarios", default=str(ROOT / "eval/bench/scenarios.json"))
    parser.add_argument("--model", default="mlx-community/gemma-3-1b-it-4bit")
    parser.add_argument("--temp", type=float, default=0.8)
    parser.add_argument("--steps", type=int, default=700)
    parser.add_argument("--limit", type=int, default=0, help="use only the first N scenarios")
    parser.add_argument("--out", default=str(ROOT / "eval/duplex/out/turntaking_ab.json"))
    args = parser.parse_args()

    from duet_agent.fast_brain import FastBrain

    scenarios = json.loads(Path(args.scenarios).read_text())
    if args.limit:
        scenarios = scenarios[:args.limit]
    print(f"{len(scenarios)} scenarios, Piper lessac caller (July voice)\n")

    stack = build_stack(args.temp)
    print("moshi loaded\n")

    results = []
    for spec in args.arms.split(";"):
        name, _, params = spec.partition(":")
        conf = dict(kv.split("=") for kv in params.split(","))
        quiet, delay = int(conf["q"]), float(conf["delay"])
        brain = FastBrain(model_id=args.model, delay_ms=delay)
        brain.request([], "warmup")
        while brain.poll() is None:
            time.sleep(0.005)

        calls = []
        for scenario in scenarios:
            summary, counters = run_call(stack, scenario, brain, quiet, args.steps)
            calls.append({"scenario": scenario["id"], **summary, **counters})
            print(f"  [{name}] {scenario['id']:<20} takeover {summary['takeover_rate']:.2f} "
                  f"handoff p50 {summary['response_latency_ms_p50']} ms", flush=True)

        def mean(key):
            vals = [c[key] for c in calls if c[key] is not None]
            return round(float(np.mean(vals)), 3) if vals else None

        agg = {
            "arm": name, "quiet_frames": quiet, "delay_ms": delay, "calls": len(calls),
            "takeover_rate": mean("takeover_rate"),
            "overlap_ratio": mean("overlap_ratio"),
            "handoff_p50_ms": mean("response_latency_ms_p50"),
            "handoff_p95_ms": mean("response_latency_ms_p95"),
            "backchannels_per_call": mean("backchannels"),
            "takeovers_total": sum(c["takeovers"] for c in calls),
            "dropped_stale_total": sum(c["dropped_stale"] for c in calls),
            "per_call": calls,
        }
        results.append(agg)
        print(f"[{name}] takeover {agg['takeover_rate']} | overlap {agg['overlap_ratio']} | "
              f"handoff p50 {agg['handoff_p50_ms']} p95 {agg['handoff_p95_ms']} | "
              f"backchannel/call {agg['backchannels_per_call']}\n", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))

    print(f"{'arm':<10} {'takeover':>9} {'overlap':>8} {'p50 ms':>8} {'p95 ms':>9} {'bc/call':>8}")
    print(f"{'JULY':<10} {0.24:>9.2f} {0.234:>8.3f} {240:>8} {3248:>9} {0.4:>8}   <- eval/bench/RESULTS.md")
    for r in results:
        print(f"{r['arm']:<10} {r['takeover_rate']:>9.2f} {r['overlap_ratio']:>8.3f} "
              f"{r['handoff_p50_ms']:>8.0f} {r['handoff_p95_ms']:>9.0f} {r['backchannels_per_call']:>8.2f}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
