#!/usr/bin/env python3
"""Sweep steering-loop latency against a real full-duplex model.

Tests the hypothesis in docs/DUPLEX_STEERING.md: a full-duplex speech model is
steerable only while the steering loop is faster than the model's own
utterance-planning horizon. Moshi emits one frame every 80 ms, so a steering
loop of L ms lets the model free-run for roughly L/80 frames before guidance
arrives -- and once it has committed to its own clause, injected guidance stops
being steering and becomes a second speaker.

Everything is held fixed across arms except steering latency, which is varied
via FastBrain(delay_ms=...): the brain generates at full speed and then waits,
so phrasing and content are identical and latency is the sole independent
variable. Caller audio is cached Sarvam speech (see --fixtures), so arms are
driven by byte-identical input.

Primary metric is free_run_tokens: how many of its own words Moshi speaks
between the caller finishing and injection actually starting.

    python eval/duplex/sweep_steering_latency.py --arms 170,300,600,900,1300
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

FRAME = 1920
FRAME_MS = 80.0


def load_stack(temp: float):
    """Load Moshi + Mimi once; arms reuse the weights and reset generator state."""
    import huggingface_hub
    import mlx.core as mx
    import rustymimi

    from duet_agent import local_loop as L

    args = types.SimpleNamespace(hf_repo="kyutai/moshiko-mlx-q4", quantized=4, steps=4000, temp=temp)
    holder: dict = {"injector": None}

    def hook(text_tokens):
        injector = holder["injector"]
        if injector is None:
            return
        sampled = int(np.array(text_tokens).reshape(-1)[0])
        forced = injector.hook(sampled)
        if forced != sampled:
            text_tokens[:] = mx.array([[forced]])

    import mlx.nn as nn
    import sentencepiece
    from moshi_mlx import models, utils

    weights = huggingface_hub.hf_hub_download(args.hf_repo, "model.q4.safetensors")
    sp = sentencepiece.SentencePieceProcessor(
        huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer_spm_32k_3.model"))
    model = models.Lm(models.config_v0_1())
    model.set_dtype(mx.bfloat16)
    nn.quantize(model, bits=4, group_size=32)
    model.load_weights(weights, strict=True)
    model.warmup()
    mimi_file = huggingface_hub.hf_hub_download(
        args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors")

    def fresh(on_text_hook):
        """A per-arm generator + codec. Sharing these across arms let one arm's
        KV cache and conversational state leak into the next, and eventually
        overran max_steps mid-sweep."""
        gen = models.LmGen(
            model=model, max_steps=1200, text_sampler=utils.Sampler(),
            audio_sampler=utils.Sampler(temp=args.temp), check=False,
            on_text_hook=on_text_hook,
        )
        return gen, rustymimi.StreamTokenizer(mimi_file)  # type: ignore[attr-defined]

    return L, fresh, sp, hook, holder, mx


def encode(mimi, mx, pcm: np.ndarray) -> list[np.ndarray]:
    """PCM at 24 kHz -> one Mimi code frame per 80 ms."""
    frames = []
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        mimi.encode(np.ascontiguousarray(pcm[i:i + FRAME], dtype=np.float32))
        deadline = time.time() + 5.0
        while (data := mimi.get_encoded()) is None:
            if time.time() > deadline:
                raise RuntimeError("Mimi encoder stalled")
            time.sleep(0.001)
        frames.append(data)
    return frames


def looks_committed(text: str) -> bool:
    """Has Moshi's free-run output already formed a clause it owns?

    A committed clause is what makes late guidance sound like an interruption
    rather than a plan: sentence-final punctuation, or enough words that the
    model has clearly chosen a direction.
    """
    stripped = text.strip()
    if not stripped:
        return False
    return bool(re.search(r"[.!?]", stripped)) or len(stripped.split()) >= 5


def run_arm(stack, delay_ms: float, fixtures: list[np.ndarray], model_id: str, quiet_frames: int):
    from duet_agent.fast_brain import FastBrain
    from duet_agent.injector import TextInjector

    L, fresh, sp, hook, holder, mx = stack
    gen, mimi = fresh(hook)

    brain = FastBrain(model_id=model_id, delay_ms=delay_ms)
    injector = TextInjector(
        encode=lambda s: sp.encode(s),
        quiet_frames_to_start=quiet_frames,
        pace_pads=2,
    )
    holder["injector"] = injector

    # Warm the brain so first-call compile cost is not charged to the arm.
    brain.request([], "warmup")
    while brain.poll() is None:
        time.sleep(0.005)

    per_turn = []
    history: list[tuple[str, str]] = []

    for pcm in fixtures:
        caller_frames = encode(mimi, mx, pcm)

        # --- caller speaks; Moshi listens (and may backchannel) ---
        for frame in caller_frames:
            injector.on_user_frame(float(np.sqrt(np.mean(pcm[:FRAME] ** 2))))
            L.step_once(gen, sp, frame)

        # --- caller stops: fire the steering request, keep the model running ---
        brain.request(history, "caller utterance")
        free_run: list[str] = []
        injection_started_frame = None
        steer = None
        silence = encode(mimi, mx, np.zeros(FRAME, dtype=np.float32))[0]

        for frame_index in range(120):  # 9.6 s ceiling
            injector.on_user_frame(0.0)  # caller is quiet now
            state_before = injector.state
            _, piece = L.step_once(gen, sp, silence)
            if steer is None:
                result = brain.poll()
                if result is not None and getattr(result, "text", ""):
                    steer = result
                    injector.inject(result.text)
            # Count only words Moshi chose itself, before forcing begins.
            if injection_started_frame is None:
                if str(injector.state) != str(state_before) and "FORCING" in str(injector.state):
                    injection_started_frame = frame_index
                elif piece:
                    free_run.append(piece)
            if injection_started_frame is not None and injector.state.name == "IDLE":
                break

        free_text = "".join(free_run)
        per_turn.append({
            "free_run_tokens": len(free_run),
            "free_run_text": free_text.strip()[:120],
            "committed_before_guidance": looks_committed(free_text),
            "injection_start_frame": injection_started_frame,
            "steer_total_ms": round(steer.total_ms, 1) if steer else None,
            "spoke_guidance": injection_started_frame is not None,
        })
        history.append(("caller", "caller utterance"))
        if steer:
            history.append(("you", steer.text))

    turns = len(per_turn)
    return {
        "delay_ms": delay_ms,
        "turns": turns,
        "mean_free_run_tokens": round(sum(t["free_run_tokens"] for t in per_turn) / turns, 2),
        "committed_rate": round(sum(t["committed_before_guidance"] for t in per_turn) / turns, 3),
        "spoke_guidance_rate": round(sum(t["spoke_guidance"] for t in per_turn) / turns, 3),
        "injected": injector.injected,
        "dropped_stale": injector.dropped_stale,
        "cancelled_by_barge_in": injector.cancelled_by_barge_in,
        "median_steer_ms": round(
            float(np.median([t["steer_total_ms"] for t in per_turn if t["steer_total_ms"]])), 1
        ) if any(t["steer_total_ms"] for t in per_turn) else None,
        "turn_detail": per_turn,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="170,300,600,900,1300",
                        help="steering latencies in ms; 1300 reproduces the July Gemini loop")
    parser.add_argument("--fixtures", default="/tmp/duplex_fixtures")
    parser.add_argument("--model", default="mlx-community/gemma-3-1b-it-4bit")
    parser.add_argument("--temp", type=float, default=0.8)
    parser.add_argument("--quiet-frames", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=1,
                        help="cycle the fixture set N times per arm for sample size")
    parser.add_argument("--out", default=str(ROOT / "eval/duplex/out/sweep.json"))
    parser.add_argument("--sweep-quiet", default="",
                        help="comma list of quiet_frames values; sweeps the injector's politeness window instead of latency")
    args = parser.parse_args()

    paths = sorted(Path(args.fixtures).glob("*.npy"))
    if not paths:
        raise SystemExit(f"no caller fixtures in {args.fixtures}")
    fixtures = [np.load(p) for p in paths] * args.repeats
    print(f"caller fixtures: {[p.stem for p in paths]}")

    stack = load_stack(args.temp)
    print("moshi loaded\n")

    rows = []
    if args.sweep_quiet:
        combos = [(0.0, int(q)) for q in args.sweep_quiet.split(",")]
    else:
        combos = [(float(x), args.quiet_frames) for x in args.arms.split(",")]
    for delay, quiet in combos:
        row = run_arm(stack, delay, fixtures, args.model, quiet)
        row["quiet_frames"] = quiet
        rows.append(row)
        print(f"[d={delay:>5.0f}ms q={quiet}] free-run tok {row['mean_free_run_tokens']:>5.2f} | "
              f"committed {row['committed_rate']:>5.1%} | spoke {row['spoke_guidance_rate']:>5.1%} | "
              f"stale {row['dropped_stale']} | steer p50 {row['median_steer_ms']} ms", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))

    print(f"\n{'steer ms':>9} {'free-run tok':>13} {'committed':>10} {'spoke':>7} {'stale':>6}")
    for row in rows:
        print(f"{row['delay_ms']:>9.0f} {row['mean_free_run_tokens']:>13.2f} "
              f"{row['committed_rate']:>9.1%} {row['spoke_guidance_rate']:>6.1%} {row['dropped_stale']:>6}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
