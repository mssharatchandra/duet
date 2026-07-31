# ASR eval

Turns "the transcription isn't accurate" into a number, and (as of this round) into a
number that can actually tell candidates apart.

## Background — why this exists

DECISIONS 0012 built the first version of this harness: synthesize the 30 benchmark
utterances with Piper (deterministic TTS), run each ASR candidate over the audio, score
word error rate (WER) against the known ground-truth text. It found every faster-whisper
candidate sitting at ~2.3% WER, with bigger models doing *worse* and slower. That result
falsified two of this project's own prior claims (the 24kHz/16kHz sample-rate bug wasn't
actually costing accuracy on this data, and the small.en "upgrade" was a regression) — but
it also left an open problem: **the eval could not discriminate**. Piper's TTS output is
clean, unaccented, noiseless studio audio. It is nothing like what a laptop mic picks up
in a real room, so a ~2.3%-across-the-board result doesn't mean the models are actually
tied — it may just mean the test is too easy to show a gap.

This round of work had two goals: (1) make the eval harder in a controlled, honest way so
it has a chance to discriminate, and (2) evaluate Apple-Silicon-native ASR (mlx-whisper,
NVIDIA Parakeet via parakeet-mlx) alongside the existing faster-whisper candidates, since
this machine is an M5 and CPU-only ctranslate2 is leaving GPU/ANE throughput on the table.

## Method

`eval/asr/augment.py` adds five pure, seeded degradations to the clean 24kHz Piper audio:

- `add_white_noise(pcm, snr_db, seed)` — additive Gaussian white noise at a target SNR.
- `add_pink_noise(pcm, snr_db, seed)` — 1/f-shaped noise (closer to HVAC/room hiss).
- `add_reverb(pcm, seed=...)` — convolution with a synthetic room impulse response
  (direct-path spike + exponentially-decaying random reflections, RT60 = 0.3s default).
- `change_speed(pcm, factor)` — Kaldi-style speed perturbation via resampling (±10%
  changes both tempo and pitch, same as a real device's clock drift or a faster/slower
  talker).
- `gain_and_clip(pcm, gain_db, threshold)` — gain boost + hard clip, simulating a hot mic
  or AGC overshoot.

Every function is deterministic given its seed (verified in
`agent/tests/test_asr_augment.py` — same seed ⇒ bit-identical output; noise-mixing hits
its target SNR to within 0.5dB; reverb doesn't clip or change length; etc). `--augment`
mode in `run_asr_eval.py` runs every candidate model through a **matrix** of named
conditions — `clean, snr20, snr10, snr5, reverb, fast, slow` — using a per-`(condition,
clip)` seed (via `zlib.crc32`, not Python's built-in `hash()`, which is randomized per
process) so every model sees byte-identical degraded audio for a fair comparison.

**No augmentation parameter was tuned to produce a particular answer.** SNR targets
(20/10/5dB) and RT60 (0.3s) were chosen as reasonable prior values for "quiet room /
typical room / noisy room" before any model was run against them, and were not adjusted
afterward.

### Engines

`run_asr_eval.py` now supports three backends via a model-spec prefix:

| prefix | backend | notes |
|---|---|---|
| *(none)*, `fw:` | faster-whisper (ctranslate2, CPU, int8) | existing default, unchanged |
| `mlx:<hf-repo>` | mlx-whisper (MLX/Metal, Apple Silicon GPU) | new |
| `parakeet:<hf-repo>` | NVIDIA Parakeet via parakeet-mlx (MLX/Metal) | new, see install note below |

## Results

<!-- FILLED IN AFTER THE RUN — see /private/tmp/.../scratchpad/agent_asr.md for the same
     numbers reported to the task owner. -->

### WER × condition (faster-whisper baseline models)

_pending — see summary below for latest numbers as measured_

### Apple-Silicon-native candidates: WER + RTF

_pending_

### Install notes / failures

**parakeet-mlx** installs cleanly via `uv pip install parakeet-mlx` — no Python packaging
issue. But `BaseParakeet.transcribe()`'s public API takes a file path and shells out to
the `ffmpeg` binary (`parakeet_mlx.audio.load_audio` runs `ffmpeg -i ... -f s16le ...`).
**`ffmpeg` is not installed on this machine, and neither is Homebrew**, so that code path
is a hard runtime dependency failure here — not something fixable with more `pip`/`uv`
installs. `run_asr_eval.py`'s `ParakeetMlxEngine` works around it by calling the model's
own `get_logmel()` + `generate()` directly on resampled PCM, bypassing `load_audio()` and
`ffmpeg` entirely. This is documented here rather than "fixed" by installing Homebrew,
per the instruction to record install failures rather than burn time on them — the
workaround happened to be available in this case, but the missing-ffmpeg fact is still a
real deployment consideration if Duet ever ships Parakeet as an option.

## Honest limitations

- **Synthetic degradation is not a recorded room.** `augment.py` is a *proxy* — additive
  noise + a synthetic exponential-decay IR + resampled speed changes are closer to a real
  environment than dry TTS, but they are not microphone recordings of an actual user in
  an actual room. Treat `--augment` results as a *better relative ranking*, not an
  absolute accuracy number. The only way to truly settle this needs real mic recordings
  (0012's open item, still open).
- **Piper's voice, not the user's.** All conditions inherit whatever the TTS voice does
  or doesn't do well (0012 already found one TTS artifact — "Ah shame" synthesized badly
  — being blamed on the recognizer). Augmenting doesn't fix that.
- **30 utterances is a small eval set.** Per-condition WER on ~90s of audio moves in
  large discrete steps (one wrong word can shift WER by a percentage point or more) — the
  headline numbers should be read as "roughly this level," not to two decimal places.
- **RTF was measured on a shared machine.** Other CPU/GPU work was running concurrently
  during parts of this evaluation (a background model download, and unrelated work in
  this repo); RTF for CPU-bound faster-whisper models is likely a slight overestimate of
  a dedicated-machine number. MLX/Metal-backed engines share the GPU, not just CPU, so
  the same caveat applies to them too.

## Recommendation

_pending — filled in once the matrix is measured; see the final summary._

## Usage

```bash
# plain eval (unchanged CLI, backward compatible)
agent/.venv/bin/python eval/asr/run_asr_eval.py --models tiny.en,base.en,small.en

# discrimination matrix — faster-whisper only
agent/.venv/bin/python eval/asr/run_asr_eval.py --augment \
  --augment-models base.en,small.en

# discrimination matrix — including Apple-Silicon-native candidates
agent/.venv/bin/python eval/asr/run_asr_eval.py --augment \
  --augment-models "base.en,small.en,mlx:mlx-community/whisper-large-v3-turbo,parakeet:mlx-community/parakeet-tdt-0.6b-v3"

# narrower/faster smoke test
agent/.venv/bin/python eval/asr/run_asr_eval.py --augment --limit 5 \
  --augment-conditions clean,snr10,reverb
```

Writes `eval/asr/results.json` (plain mode) or `eval/asr/results_augment.json`
(`--augment` mode).
