#!/usr/bin/env python3
# Duet — ASR eval: turn "the transcription isn't accurate" into a number.
#
# Method: our benchmark scenarios have ground-truth text. Synthesize each
# utterance with Piper, run every candidate ASR config over the SAME synthesized
# clips (built once per process, reused for every model/condition — so within one
# run every candidate hears byte-identical audio), and report WER. Also measures
# real-time factor (RTF) — an ASR that is 3% better but 4x slower is not
# automatically the right pick for a live agent.
#
# HONEST LIMITATIONS, stated up front:
# - TTS speech is clean, unaccented and noiseless, so plain WERs are a LOWER
#   BOUND and a *relative* ranking — not absolute accuracy on real users.
#   --augment (see below) closes part of that gap by degrading the clean
#   synthetic audio toward a real-room proxy; it is still not recorded speech,
#   so treat it as a better relative ranking, not an absolute number either.
#   The genuinely on-distribution version of this eval needs recordings of the
#   actual user in their actual room; this harness accepts those via
#   --audio-dir once they exist.
# - Piper is NOT fully deterministic across separate process runs, despite
#   earlier versions of this comment claiming otherwise: it's a VITS-style
#   model whose decoder samples a noise latent inside the ONNX graph on every
#   call, unseeded. Same-run comparisons (the normal case here) are unaffected
#   since `clips` is built once and reused; only cross-run WER comparisons for
#   "the same" condition/model can drift by a few points. See eval/asr/README.md.
#
# --augment mode (DECISIONS 0012 follow-up): the plain eval put every
# faster-whisper candidate within a point of each other (~2.3% WER) — too flat
# to discriminate between models. --augment reruns every model across a matrix
# of degraded conditions (noise at a few SNRs, reverb, speed perturbation) via
# eval/asr/augment.py, on the theory that a harder, more realistic signal will
# spread the candidates out if there's a real difference to find. It might not
# — that itself is a reportable result, not a bug to fix by re-tuning the
# augmentations until something moves.
#
# Model spec syntax (both --models and --augment-models): "name" or "fw:name"
# selects faster-whisper (default, backward compatible with pre-augment specs);
# "mlx:<hf-repo>" selects mlx-whisper (Apple Silicon native); "parakeet:<hf-repo>"
# selects NVIDIA Parakeet via parakeet-mlx (Apple Silicon native).
#
# Usage:
#   agent/.venv/bin/python eval/asr/run_asr_eval.py [--models small.en,...]
#   agent/.venv/bin/python eval/asr/run_asr_eval.py --augment [--augment-models ...]

import argparse
import json
import re
import sys
import time
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

from duet_agent.asr_util import to_whisper_rate  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from augment import CONDITIONS, apply_condition  # noqa: E402

SCENARIOS = ROOT / "eval" / "bench" / "scenarios.json"
DEFAULT_MODELS = "tiny.en,base.en,small.en,distil-large-v3"
DEFAULT_AUGMENT_MODELS = "base.en,small.en,mlx:mlx-community/whisper-large-v3-turbo,parakeet:mlx-community/parakeet-tdt-0.6b-v3"
DEFAULT_AUGMENT_CONDITIONS = "clean,snr20,snr10,snr5,reverb,fast,slow"

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


# ---------------------------------------------------------------------------
# Engines: one small adapter per ASR backend, all exposing load()/transcribe().
# This is what lets --models mix faster-whisper, mlx-whisper and parakeet-mlx
# candidates in the same run.


def _parse_model_spec(spec: str) -> tuple[str, str]:
    """'base.en' -> ('fw', 'base.en'); 'mlx:mlx-community/whisper-large-v3-turbo'
    -> ('mlx', 'mlx-community/whisper-large-v3-turbo'). No-prefix defaults to
    faster-whisper so pre-existing --models values keep working unchanged."""
    if ":" in spec:
        kind, name = spec.split(":", 1)
        if kind in ("fw", "mlx", "parakeet"):
            return kind, name
    return "fw", spec


class FasterWhisperEngine:
    label_prefix = ""

    def __init__(self, name: str, resample: bool = True):
        self.name = name
        self.resample = resample
        self._model = None

    def load(self) -> float:
        from faster_whisper import WhisperModel

        t0 = time.perf_counter()
        self._model = WhisperModel(self.name, device="cpu", compute_type="int8")
        return time.perf_counter() - t0

    def transcribe(self, pcm24k: np.ndarray) -> tuple[str, float]:
        audio = to_whisper_rate(pcm24k) if self.resample else pcm24k
        t0 = time.perf_counter()
        segments, _ = self._model.transcribe(audio, language="en", beam_size=1)
        text = " ".join(s.text.strip() for s in segments)
        return text, time.perf_counter() - t0


class MlxWhisperEngine:
    """MLX-native Whisper — runs on the GPU via Metal instead of CPU-only
    ctranslate2. mlx_whisper.transcribe() caches the loaded model in a module-
    level singleton keyed by repo id, so only the *first* call pays weight-load
    cost; we pay that cost explicitly in load() with a short warm-up clip so
    per-clip transcribe() timings measure inference only."""

    label_prefix = "mlx:"

    def __init__(self, repo: str):
        self.repo = repo
        self._mlx_whisper = None

    def load(self) -> float:
        import mlx_whisper

        self._mlx_whisper = mlx_whisper
        t0 = time.perf_counter()
        warm = np.zeros(16_000, dtype=np.float32)  # 1s silence @ 16kHz — triggers weight download + load
        self._mlx_whisper.transcribe(warm, path_or_hf_repo=self.repo, language="en", verbose=False)
        return time.perf_counter() - t0

    def transcribe(self, pcm24k: np.ndarray) -> tuple[str, float]:
        audio16 = to_whisper_rate(pcm24k)
        t0 = time.perf_counter()
        result = self._mlx_whisper.transcribe(audio16, path_or_hf_repo=self.repo, language="en", verbose=False)
        return result["text"], time.perf_counter() - t0


class ParakeetMlxEngine:
    """NVIDIA Parakeet via parakeet-mlx (Apple Silicon native, MLX/Metal).
    NOTE: BaseParakeet.transcribe()'s public API takes a file path and shells
    out to the `ffmpeg` binary to decode it (parakeet_mlx.audio.load_audio).
    ffmpeg is not installed on this machine and neither is Homebrew, so that
    path is unusable here (see README's "install failures" section) — this
    bypasses it and feeds resampled PCM straight through the model's own
    get_logmel + generate(), which needs no ffmpeg at all."""

    label_prefix = "parakeet:"

    def __init__(self, repo: str):
        self.repo = repo
        self._model = None

    def load(self) -> float:
        from parakeet_mlx import from_pretrained

        t0 = time.perf_counter()
        self._model = from_pretrained(self.repo)
        # Warm up MLX's lazy graph compilation with a throwaway clip so per-clip
        # transcribe() timings measure steady-state inference, not first-call JIT
        # cost (observed ~4x slower on the very first real call otherwise).
        self.transcribe(np.zeros(24_000, dtype=np.float32))
        return time.perf_counter() - t0

    def transcribe(self, pcm24k: np.ndarray) -> tuple[str, float]:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        sr = self._model.preprocessor_config.sample_rate
        n = len(pcm24k)
        m = max(round(n * sr / 24_000), 1)
        audio = np.interp(np.linspace(0, n - 1, m), np.arange(n), pcm24k).astype(np.float32)
        t0 = time.perf_counter()
        mel = get_logmel(mx.array(audio), self._model.preprocessor_config)
        result = self._model.generate(mel)[0]
        return result.text, time.perf_counter() - t0


def make_engine(spec: str, resample: bool = True):
    kind, name = _parse_model_spec(spec)
    if kind == "fw":
        return FasterWhisperEngine(name, resample=resample)
    if kind == "mlx":
        return MlxWhisperEngine(name)
    if kind == "parakeet":
        return ParakeetMlxEngine(name)
    raise ValueError(f"unknown engine kind: {kind!r}")


def label_for(spec: str, resample: bool = True) -> str:
    kind, name = _parse_model_spec(spec)
    prefix = {"fw": "", "mlx": "mlx:", "parakeet": "parakeet:"}[kind]
    suffix = "" if resample else "  [24kHz BUG]"
    return f"{prefix}{name}{suffix}"


# ---------------------------------------------------------------------------
# Plain (non-augment) eval — unchanged behavior from before, generalized to
# run any engine spec instead of only faster-whisper.


def evaluate(spec: str, clips: list[tuple[str, np.ndarray]], resample: bool) -> dict:
    engine = make_engine(spec, resample=resample)
    load_s = engine.load()

    errors = length = 0
    audio_s = infer_s = 0.0
    worst: tuple[float, str, str] = (0.0, "", "")
    for truth, pcm in clips:
        text, dt = engine.transcribe(pcm)
        infer_s += dt
        audio_s += len(pcm) / 24_000

        ref, hyp = normalize(truth), normalize(text)
        e, n = wer(ref, hyp)
        errors += e
        length += n
        if n and e / n >= worst[0]:
            worst = (e / n, truth, text.strip())

    return {
        "model": spec,
        "resample": resample,
        "wer": errors / max(length, 1),
        "rtf": infer_s / max(audio_s, 1e-9),
        "load_s": load_s,
        "worst": worst,
    }


def run_plain(args, clips: list[tuple[str, np.ndarray]]) -> int:
    runs = []
    # The control: reproduce the sample-rate bug we fixed, to quantify what it cost.
    if not args.skip_bug_check:
        runs.append(evaluate("small.en", clips, resample=False))
    runs += [evaluate(m.strip(), clips, resample=True) for m in args.models.split(",")]

    print(f"{'config':34s} {'WER':>8s} {'RTF':>7s} {'load':>7s}")
    print("-" * 60)
    for r in runs:
        label = label_for(r["model"], resample=r["resample"])
        print(f"{label:34s} {r['wer']:7.1%} {r['rtf']:6.2f}x {r['load_s']:6.1f}s")

    best = min((r for r in runs if r["resample"]), key=lambda r: r["wer"])
    print(f"\nbest by WER: {label_for(best['model'])} at {best['wer']:.1%} (RTF {best['rtf']:.2f}x)")
    rate, truth, heard = best["worst"]
    if truth:
        print(f"worst remaining case ({rate:.0%} WER):\n  said:  {truth}\n  heard: {heard}")
    print("\nNOTE: TTS speech is clean — treat these as a relative ranking and a lower bound,")
    print("not absolute accuracy. Re-run with real recordings for an on-distribution number.")
    print("Re-run with --augment to test whether the eval can discriminate models under noise/reverb.")

    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps([{k: v for k, v in r.items() if k != "worst"} for r in runs], indent=2))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------------------
# --augment mode: WER × condition × model matrix.


def evaluate_augmented(spec: str, clips: list[tuple[str, np.ndarray]], conditions: list[str]) -> dict:
    """One engine load, all conditions and clips run through it — avoids paying
    model-load cost once per condition."""
    engine = make_engine(spec, resample=True)
    load_s = engine.load()
    print(f"  loaded in {load_s:.1f}s", flush=True)

    per_condition: dict[str, dict] = {}
    for cond in conditions:
        cond_t0 = time.perf_counter()
        errors = length = 0
        audio_s = infer_s = 0.0
        worst: tuple[float, str, str] = (0.0, "", "")
        for i, (truth, pcm) in enumerate(clips):
            # seed per (condition, clip index) — deterministic and independent of
            # model/run order, so every candidate sees byte-identical degraded audio.
            # NOTE: built-in hash() is process-randomized for str/tuple (PYTHONHASHSEED),
            # so it cannot be used here despite being tempting; crc32 is stable.
            seed = zlib.crc32(f"{cond}:{i}".encode())
            degraded = apply_condition(cond, pcm, seed=seed)

            text, dt = engine.transcribe(degraded)
            infer_s += dt
            audio_s += len(degraded) / 24_000

            ref, hyp = normalize(truth), normalize(text)
            e, n = wer(ref, hyp)
            errors += e
            length += n
            if n and e / n >= worst[0]:
                worst = (e / n, truth, text.strip())

        cond_wer = errors / max(length, 1)
        cond_rtf = infer_s / max(audio_s, 1e-9)
        per_condition[cond] = {"wer": cond_wer, "rtf": cond_rtf, "worst": worst}
        print(f"  {cond:8s} wer={cond_wer:6.1%} rtf={cond_rtf:5.2f}x ({time.perf_counter() - cond_t0:.1f}s)", flush=True)

    return {"model": spec, "load_s": load_s, "conditions": per_condition}


def run_augment(args, clips: list[tuple[str, np.ndarray]]) -> int:
    conditions = [c.strip() for c in args.augment_conditions.split(",")]
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown:
        print(f"unknown condition(s): {unknown} — choose from {list(CONDITIONS)}", file=sys.stderr)
        return 2

    specs = [m.strip() for m in args.augment_models.split(",")]
    print(f"--augment: {len(specs)} model(s) x {len(conditions)} condition(s) x {len(clips)} clip(s)\n")

    results = []
    for spec in specs:
        print(f"running {label_for(spec)} ...")
        try:
            results.append(evaluate_augmented(spec, clips, conditions))
        except Exception as exc:  # noqa: BLE001 — a broken candidate is a reportable finding, not a crash
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            results.append({"model": spec, "load_s": None, "conditions": {}, "error": f"{type(exc).__name__}: {exc}"})

    # WER matrix
    col_w = 10
    header = f"{'model':38s}" + "".join(f"{c:>{col_w}s}" for c in conditions)
    print("\nWER by condition\n" + header + "\n" + "-" * len(header))
    for r in results:
        if r.get("error"):
            print(f"{label_for(r['model']):38s}  ERROR: {r['error']}")
            continue
        row = f"{label_for(r['model']):38s}"
        for c in conditions:
            row += f"{r['conditions'][c]['wer']:>{col_w}.1%}"
        print(row)

    # RTF matrix (informational — flags anything unusable live, RTF >= 1.0x)
    print("\nRTF by condition (>= 1.0x is unusable for a live agent)\n" + header + "\n" + "-" * len(header))
    for r in results:
        if r.get("error"):
            continue
        row = f"{label_for(r['model']):38s}"
        for c in conditions:
            row += f"{r['conditions'][c]['rtf']:>{col_w - 1}.2f}x"
        print(row)

    print("\nload times: " + ", ".join(f"{label_for(r['model'])}={r['load_s']:.1f}s" for r in results if r.get("load_s") is not None))

    out = Path(__file__).parent / "results_augment.json"
    out.write_text(json.dumps(results, indent=2, default=lambda o: list(o) if isinstance(o, tuple) else o))
    print(f"wrote {out.relative_to(ROOT)}")

    print("\nNOTE: augmentations are a proxy for a real room, not recordings of one. If the")
    print("ranking still doesn't move under noise/reverb, that says our eval has a ceiling")
    print("problem, not that the models are actually tied on real speech.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--limit", type=int, default=0, help="only the first N utterances")
    ap.add_argument("--skip-bug-check", action="store_true",
                    help="skip the 24kHz-fed-as-16kHz control (DECISIONS 0009)")
    ap.add_argument("--augment", action="store_true",
                    help="run the WER x condition x model discrimination matrix instead of the plain eval")
    ap.add_argument("--augment-models", default=DEFAULT_AUGMENT_MODELS,
                    help="comma-separated model specs for --augment mode; prefix mlx:/parakeet: for Apple-Silicon-native engines")
    ap.add_argument("--augment-conditions", default=DEFAULT_AUGMENT_CONDITIONS,
                    help=f"comma-separated conditions for --augment mode, from {list(CONDITIONS)}")
    args = ap.parse_args()

    texts = utterances()
    if args.limit:
        texts = texts[: args.limit]
    print(f"synthesizing {len(texts)} utterances with Piper …")
    clips = [(t, synth(t)) for t in texts]
    total_s = sum(len(p) / 24_000 for _, p in clips)
    print(f"{total_s:.1f}s of audio · ground truth = scenario text\n")

    if args.augment:
        return run_augment(args, clips)
    return run_plain(args, clips)


if __name__ == "__main__":
    raise SystemExit(main())
