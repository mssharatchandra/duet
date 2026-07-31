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

Primary source: **one single invocation** of
`agent/.venv/bin/python eval/asr/run_asr_eval.py --augment --augment-models
"base.en,small.en,mlx:mlx-community/whisper-large-v3-turbo,parakeet:mlx-community/parakeet-tdt-0.6b-v3"`
— all 30 benchmark utterances (~88s of audio), all 7 conditions, all 4 models in one
process, so every model heard byte-identical audio per condition (`clips` is synthesized
once and reused — see Method). This is the most defensible single comparison in this
round; secondary/isolated per-model runs are referenced in "Honest limitations" below to
show run-to-run and contention variance, not as a competing source of truth.

### WER × condition (single combined run, byte-identical audio per model)

| model | clean | snr20 | snr10 | snr5 | reverb | fast | slow |
|---|---:|---:|---:|---:|---:|---:|---:|
| base.en (faster-whisper) | 4.2% | 5.7% | 7.6% | 14.1% | 4.2% | 4.9% | 4.2% |
| small.en (faster-whisper) | 3.0% | 3.0% | 4.9% | 8.7% | 2.7% | 3.0% | 3.0% |
| mlx-whisper-large-v3-turbo | 2.3% | 1.5% | 1.9% | 3.4% | 2.7% | 1.9% | 2.7% |
| **parakeet-tdt-0.6b-v3** | **1.9%** | **1.5%** | 2.7% | **2.7%** | **1.9%** | **1.9%** | **1.5%** |

**This is the headline result: the eval now discriminates.** On clean synthetic speech,
0012 found every faster-whisper model within a point of 2.3% WER — flat, unable to pick a
winner. Under this same battery, a clear ranking opens up and holds across every
condition: **parakeet ≈ mlx-whisper-large-v3-turbo < small.en < base.en**, every candidate
beating base.en by 1.5-5x, with the gap *widening* as conditions get harder (base.en vs.
parakeet: 2.2x worse at clean, 5.2x worse at snr5).

**This also reverses one of 0012's own corrections.** 0012 found small.en *worse* than
base.en on clean TTS (2.7% vs. 2.3%) and reverted the default to base.en. In this run,
small.en beats base.en in *every* condition — e.g. 4.9% vs. 7.6% at snr10, 8.7% vs. 14.1%
at snr5. **DECISIONS 0012's "revert to base.en" correction is itself superseded by this
data.** (The clean-audio numbers here, 4.2%/3.0%, still don't exactly match 0012's
2.3%/2.7% — see "Piper synthesis is not fully deterministic" below for why, and why it
doesn't undermine the ranking.)

### RTF (real-time factor, lower is faster; ≥1.0x is unusable live)

| model | clean | snr20 | snr10 | snr5 | reverb | fast | slow | load |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base.en | 0.26x | 0.26x | 0.24x | 0.30x | 0.22x | 0.27x | 0.22x | 0.4s |
| small.en | 0.81x | 0.83x | 0.85x | 0.97x | **1.34x** | **1.42x** | 0.88x | 1.0s |
| mlx-whisper-large-v3-turbo | 0.87x | 0.72x | 0.73x | 0.68x | 0.73x | 0.83x | 0.78x | 9.3s |
| **parakeet-tdt-0.6b-v3** | **0.08x** | **0.07x** | **0.08x** | **0.08x** | **0.04x** | **0.08x** | **0.08x** | 1.9s |

This combined run happened to be a *contended* one (other work was running on the machine
throughout this session) — which turned out to be informative rather than just noisy:
**small.en's RTF crossed the 1.0x live-usability line twice** (reverb 1.34x, fast 1.42x)
under exactly the same background load that left parakeet at 0.04-0.08x, barely moved. An
earlier, less-contended isolated run of each model alone measured small.en at a steadier
0.42-0.57x and mlx-whisper-large-v3-turbo at 0.28-0.66x — both comfortably under 1.0x in
isolation. **The lesson isn't "small.en is unusably slow"** — it's that its RTF margin is
thin enough (roughly 2x headroom in the best case) to be contention-sensitive, which
matters for a full-duplex agent that's explicitly documented (DECISIONS 0008) to share
this machine with other GPU/CPU-heavy work. parakeet's RTF was 10-33x lower than small.en's
across the 7 conditions in this same contended run — a materially different safety margin,
not just a smaller number.

### Apple-Silicon-native candidates: install notes and the parakeet-mlx/ffmpeg failure

Both `mlx-whisper` and `parakeet-mlx` installed cleanly via `uv pip install` — no Python
packaging failures for either. mlx-whisper's public `transcribe()` API works as documented
out of the box.

**parakeet-mlx needed a workaround, documented here rather than "fixed."**
`BaseParakeet.transcribe()`'s public API takes a file path and shells out to the `ffmpeg`
binary (`parakeet_mlx.audio.load_audio` runs `ffmpeg -i ... -f s16le ...`). **`ffmpeg` is
not installed on this machine, and neither is Homebrew**, so that code path is a hard
runtime dependency failure here — not a Python packaging problem, and not something more
`pip`/`uv` installs fix. `run_asr_eval.py`'s `ParakeetMlxEngine` works around it by calling
the model's own `get_logmel()` + `generate()` directly on resampled PCM, bypassing
`load_audio()` and `ffmpeg` entirely. Per the instruction to record install failures
rather than burn time on them, installing Homebrew from scratch just to get `ffmpeg` was
not attempted — the workaround happened to be available instead, but the missing-`ffmpeg`
fact is a real deployment consideration if Duet ever ships parakeet-mlx's own file-path
API rather than this bypass.

## Honest limitations

- **Piper synthesis is not fully deterministic across process runs, despite this file's
  original docstring calling it "deterministic."** Piper is a VITS-style model: its
  decoder samples a noise latent (`noise_scale`/`noise_w_scale`) *inside the ONNX graph*
  on every call, and that sampling is not seeded by anything this harness controls. Within
  a single process run, `clips` is built once and reused for every model/condition, so the
  WER/RTF tables above (one combined run) are on byte-identical audio across all 4 models
  and stay fair to compare *between models*. But two *separate* runs of "base.en, clean
  audio" measured 4.2% (the combined run above) vs. 3.8% (an earlier isolated base.en run,
  this same round) vs. 2.3% (0012, a different round entirely) — same model, same text,
  different synthesized bytes each time. So exact decimal WER shouldn't be compared
  digit-for-digit *across separate runs/rounds*, only within one run. The *ranking* found
  here (parakeet ≈ mlx-turbo < small.en < base.en) is large and consistent enough across
  all 7 conditions in the one combined run that this noise doesn't call it into question —
  but it's a real gap in the harness's own honesty claims, worth fixing (seed or cache the
  synthesized corpus to disk) before this becomes a CI gate.
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
- **RTF was measured on a shared, contended machine, and it showed.** The combined run
  reported above ran alongside a large concurrent model download and unrelated work
  elsewhere in this repo. An earlier, less-contended isolated run of each model alone
  (one model at a time, nothing else running) measured small.en at a steadier 0.42-0.57x
  and mlx-whisper-large-v3-turbo at 0.28-0.66x, vs. 0.81-1.42x and 0.68-0.87x respectively
  in the contended combined run — 2-3x higher purely from machine load, no model change.
  base.en and parakeet were comparatively stable across both. This README reports the
  contended combined-run numbers as primary (they're the ones with byte-identical audio
  across all 4 models), which arguably makes them the *more* honest numbers to report,
  not less — a live agent's ASR doesn't get to run on a quiet machine either. **RTF
  headroom, not just clearing 1.0x once, is itself a decision-relevant number** — see
  recommendation below.

## Recommendation

**Default should move from `base.en` to `parakeet-tdt-0.6b-v3` (via parakeet-mlx),
pending a spot-check on real microphone audio before it ships.**

Evidence:

1. **Best or tied-best WER in 6 of 7 conditions**, and lowest WER overall, by a clear
   margin over the current default — 1.9-2.7% vs. base.en's 4.2-14.1% at the noisier
   conditions that matter most (a live agent's mic input is never as clean as the "clean"
   column). The one exception: mlx-whisper-large-v3-turbo edged it out at snr10 (1.9% vs.
   2.7%) — small enough, on a 30-utterance set, to not change the overall picture, but
   reported plainly rather than rounded away.
2. **Best RTF by far, and the most contention-resistant.** 0.04-0.08x in the same
   contended run where small.en crossed 1.0x twice — parakeet's RTF was 10-33x lower than
   small.en's across every condition in that run. A live full-duplex agent sharing a
   machine with Moshi (DECISIONS 0008 already documents GPU contention wrecking the
   real-time budget once) needs headroom, not just a pass on a quiet benchmark.
3. **mlx-whisper-large-v3-turbo is a reasonable second choice** — best WER at snr10,
   competitive everywhere else, comfortably under 1.0x RTF even under contention (0.68-
   0.87x) — but parakeet wins on WER overall and by a wide margin on RTF headroom, so
   there's no case for mlx-whisper as the *default* given this data. It's a fine fallback
   if parakeet's ffmpeg-free workaround (point 4) turns out not to be viable in production.
4. **If parakeet ships, `ffmpeg` needs to be a documented/installed dependency** for any
   code path that uses parakeet-mlx's own `transcribe()` (file-path API); this eval
   avoided that by bypassing it (see install notes), but that workaround reaches into
   parakeet_mlx's internals (`get_logmel`, `preprocessor_config`) and isn't something to
   build production reliance on without either vendoring the workaround properly or
   installing `ffmpeg` (which requires Homebrew, also not present on this machine —
   neither was attempted here, both are environment setup, not eval scope).

**What would change this recommendation:** real microphone recordings that show parakeet
mishandling something Piper-plus-augmentation can't produce (an accent, true room echo,
overlapping/barge-in speech — Duet's actual use case, per `scenarios.json`'s `barge:
true` turns, which this eval still doesn't model at the audio level). That remains
0012's open item and is still open after this round.

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
