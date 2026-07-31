#!/usr/bin/env python3
# Duet — ASR eval: turn "the transcription isn't accurate" into a number.
#
# Method: our benchmark scenarios have ground-truth text. Synthesize each
# utterance with Piper (deterministic), run every candidate ASR config over it,
# and report WER. Also measures real-time factor (RTF) — an ASR that is 3%
# better but 4x slower is not automatically the right pick for a live agent.
#
# HONEST LIMITATION, stated up front: TTS speech is clean, unaccented and
# noiseless, so these WERs are a LOWER BOUND and a *relative* ranking — not
# absolute accuracy on real users. The genuinely on-distribution version of
# this eval needs recordings of the actual user in their actual room; this
# harness accepts those via --audio-dir once they exist.
#
# Usage: agent/.venv/bin/python eval/asr/run_asr_eval.py [--models small.en,...]

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

from duet_agent.asr_util import to_whisper_rate  # noqa: E402

SCENARIOS = ROOT / "eval" / "bench" / "scenarios.json"
DEFAULT_MODELS = "tiny.en,base.en,small.en,distil-large-v3"

_PUNCT = re.compile(r"[^\w\s']")
_WS = re.compile(r"\s+")


def normalize(text: str) -> list[str]:
    """Lowercase, drop punctuation, collapse whitespace. Deliberately simple and
    identical for every candidate so the comparison stays fair."""
    text = _PUNCT.sub(" ", text.lower().replace("—", " "))
    return _WS.sub(" ", text).strip().split()


def wer(reference: list[str], hypothesis: list[str]) -> tuple[int, int]:
    """Levenshtein distance over words → (errors, reference_length)."""
    prev = list(range(len(hypothesis) + 1))
    for i, r in enumerate(reference, 1):
        cur = [i]
        for j, h in enumerate(hypothesis, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1], len(reference)


def utterances() -> list[str]:
    return [t["text"] for sc in json.loads(SCENARIOS.read_text()) for t in sc["turns"]]


_voice = None


def synth(text: str) -> np.ndarray:
    """Piper → float32 @ 24 kHz, matching Duet's pipeline rate."""
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
    n_out = int(len(pcm) * 24_000 / _voice.config.sample_rate)
    return np.interp(np.linspace(0, len(pcm) - 1, n_out), np.arange(len(pcm)), pcm).astype(np.float32)


def evaluate(model_name: str, clips: list[tuple[str, np.ndarray]], resample: bool) -> dict:
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    asr = WhisperModel(model_name, device="cpu", compute_type="int8")
    load_s = time.perf_counter() - t0

    errors = length = 0
    audio_s = infer_s = 0.0
    worst: tuple[float, str, str] = (0.0, "", "")
    for truth, pcm in clips:
        audio = to_whisper_rate(pcm) if resample else pcm
        t0 = time.perf_counter()
        segments, _ = asr.transcribe(audio, language="en", beam_size=1)
        text = " ".join(s.text.strip() for s in segments)
        infer_s += time.perf_counter() - t0
        audio_s += len(pcm) / 24_000

        ref, hyp = normalize(truth), normalize(text)
        e, n = wer(ref, hyp)
        errors += e
        length += n
        if n and e / n >= worst[0]:
            worst = (e / n, truth, text.strip())

    return {
        "model": model_name,
        "resample": resample,
        "wer": errors / max(length, 1),
        "rtf": infer_s / max(audio_s, 1e-9),
        "load_s": load_s,
        "worst": worst,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--limit", type=int, default=0, help="only the first N utterances")
    ap.add_argument("--skip-bug-check", action="store_true",
                    help="skip the 24kHz-fed-as-16kHz control (DECISIONS 0009)")
    args = ap.parse_args()

    texts = utterances()
    if args.limit:
        texts = texts[: args.limit]
    print(f"synthesizing {len(texts)} utterances with Piper …")
    clips = [(t, synth(t)) for t in texts]
    total_s = sum(len(p) / 24_000 for _, p in clips)
    print(f"{total_s:.1f}s of audio · ground truth = scenario text\n")

    runs = []
    # The control: reproduce the sample-rate bug we fixed, to quantify what it cost.
    if not args.skip_bug_check:
        runs.append(evaluate("small.en", clips, resample=False))
    runs += [evaluate(m.strip(), clips, resample=True) for m in args.models.split(",")]

    print(f"{'config':34s} {'WER':>8s} {'RTF':>7s} {'load':>7s}")
    print("-" * 60)
    for r in runs:
        label = r["model"] + ("" if r["resample"] else "  [24kHz BUG]")
        print(f"{label:34s} {r['wer']:7.1%} {r['rtf']:6.2f}x {r['load_s']:6.1f}s")

    best = min((r for r in runs if r["resample"]), key=lambda r: r["wer"])
    print(f"\nbest by WER: {best['model']} at {best['wer']:.1%} (RTF {best['rtf']:.2f}x)")
    rate, truth, heard = best["worst"]
    if truth:
        print(f"worst remaining case ({rate:.0%} WER):\n  said:  {truth}\n  heard: {heard}")
    print("\nNOTE: TTS speech is clean — treat these as a relative ranking and a lower bound,")
    print("not absolute accuracy. Re-run with real recordings for an on-distribution number.")

    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps([{k: v for k, v in r.items() if k != "worst"} for r in runs], indent=2))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
