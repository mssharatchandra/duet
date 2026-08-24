# Duplex steering: controllability is a latency property, not a model property

**Status: direction refuted, 2026-08-24.** Two independent failures. (1) The threshold claim —
that a full-duplex model becomes reliably steerable below some critical steering latency — did not
survive its own sweep: the response is smooth, with no knee. (2) The consolation result — a 4.9x
reduction in free-run tokens — **did not survive validation on real turn-taking metrics**: the
configuration that produced it is *worse* on takeover rate, overlap, handoff latency and
backchannel count than the slow configuration it was supposed to beat. `free_run_tokens` was an
actively misleading proxy. The load-bearing finding is the opposite of the thesis: the injector's
politeness window is protective, and steering latency was never the binding constraint on duplex
control. Do not cite this document for a latency win.

## The observation this starts from

Duet's own July benchmark (`eval/bench/RESULTS.md`, Apple M5, 10 scenarios) measured:

| mode | handoff p50 | handoff p95 | takeover rate | backchannels/call |
|---|---:|---:|---:|---:|
| Moshi full-duplex | **240 ms** | 3,248 ms | 0.24 | 0.4 |
| cascade | 1,880 ms | 2,204 ms | 0.00 | 0.0 |

The full-duplex core was **8× faster at the median** eleven months ago. It was then removed as the
default (0016) and replaced with a guarded cascade that measures **1,753–2,133 ms** today (0030).

The project traded an 8× latency win for reliability. That trade is usually described as inherent:
full-duplex models are fast but uncontrollable, cascades are controllable but slow. This document
argues that framing hides the actual variable.

## Why the model rambled

Moshi was not removed for being slow. It was removed for grabbing the floor (0.24 takeover rate)
and for rambling off-script. Both are *content-control* failures.

Control over Moshi is exercised by `injector.py`: `LmGen(on_text_hook=…)` receives each frame's
sampled text token before the depformer generates that frame's audio, and overwriting the token
makes Moshi speak the forced word in its own voice and prosody. This is Kyutai's own forcing
mechanism, not a hack. But it only steers the model **while guidance is available**. Until then,
`hook()` returns `sampled_token` unchanged — the model free-runs.

Now put a number on the free-run window. Moshi emits one frame every **80 ms** (12.5 Hz Mimi).
The steering loop in July was Gemini at ~**1,281 ms** (0006):

```
free-run frames  =  steering latency / 80 ms
```

| steering loop | measured | free-run frames before guidance lands |
|---|---:|---:|
| Gemini, July (0006) | 1,281 ms | **~16** |
| Gemini, live pipeline today (0030) | 1,505–1,717 ms | **~19–21** |
| FastBrain, local KV-cached (this doc) | **221–308 ms** | **~3–4** |

Sixteen frames is roughly sixteen text tokens the model chose for itself — a complete clause,
spoken in its own voice, committed before a single word of guidance arrives. Guidance that lands
at frame 16 is not steering; it is a second speaker interrupting the first. `injector.py` already
encodes this reality defensively: rule 3 drops guidance older than 8 s unspoken, and the counters
`injected` / `cancelled_by_barge_in` / `dropped_stale` exist precisely because late guidance is a
routine event.

**The hypothesis:** what was diagnosed as "Moshi is uncontrollable" is better explained as "the
steering loop was ~16 frames slower than the model's utterance-planning horizon." Controllability
is then not a fixed property of the model but a function of steering latency, with a threshold near
the length of one self-planned clause.

## What is measured, and what is not

### Measured on this machine (2026-08-24, M5 24 GB)

**KV-caching the static prompt is the whole latency unlock.** The system prompt was being
reprocessed on every call. Prefilling it once and reusing the cache:

| configuration | TTFT | total |
|---|---:|---:|
| Gemma3-1B, full 1,981-token prompt every call | 798 ms | 1,068 ms |
| Gemma3-1B, KV-cached prompt, ~25 delta tokens | **172 ms** | 442 ms |

A 4.6× TTFT collapse, with the ~900 ms prefill paid once at startup. This is the same win Gemini's
free tier denied us (0030: `cachedContentStorageTokensPerModelFreeTier limit=0`) — but a local
model's KV cache is ours outright, which is the asymmetry that makes local worth revisiting at all.

**`FastBrain` end to end**, six-turn conversational probe, `agent/duet_agent/fast_brain.py`:

| | value |
|---|---:|
| TTFT | 184–263 ms |
| total per turn | 246–306 ms |
| **median total** | **279 ms** |
| p95 total | 306 ms |
| one-time init (load + prefill) | ~5.8 s |

### The resulting latency budget

Composing measured components only:

| component | measured | source |
|---|---:|---|
| endpointing + turn assembly | 122–204 ms | live Sarvam runs, 0030 |
| steering brain | 221–308 ms | this doc |
| Sarvam TTS first audio, warm | 220–229 ms | live runs, 0022 |
| **cascade total to first audio** | **~565–740 ms** | |

Under one second for a cascade, with headroom — versus 1,753–2,133 ms today. And in the *duplex*
configuration the TTS term disappears entirely: a frame-continuous model is already emitting audio
every 80 ms, so "start speaking" is a change in what the next frame contains, not a new synthesis
request with its own time-to-first-byte. That is the structural reason the July duplex run hit
240 ms and no cascade tuning will.

### Sweep results — the threshold hypothesis is NOT supported

Both sweeps ran against real Moshi q4 on this M5, n=12 turns per arm, byte-identical cached caller
audio, fresh generator and codec per arm (`eval/duplex/sweep_steering_latency.py`).

**A. Steering latency**, injector politeness window fixed at 6 frames:

| nominal | actual steer p50 | free-run tokens | committed before guidance |
|---:|---:|---:|---:|
| natural | 541 ms | 2.42 | 58.3% |
| 600 ms | 602 ms | 3.75 | 83.3% |
| 900 ms | 905 ms | 8.50 | 100% |
| 1300 ms | 1305 ms | 11.08 | 100% |

**B. Injector politeness window** (`quiet_frames_to_start`), brain at natural speed:

| quiet frames | window | free-run tokens | committed | steer p50 |
|---:|---:|---:|---:|---:|
| 1 | 80 ms | 2.25 | 33.3% | 286 ms |
| 2 | 160 ms | 2.25 | 58.3% | 399 ms |
| 4 | 320 ms | 4.00 | 83.3% | 402 ms |
| 6 | 480 ms | 6.17 | 66.7% | 458 ms |
| 10 | 800 ms | 5.92 | 91.7% | 347 ms |

**The predicted knee does not exist.** Free-run tokens rise smoothly and roughly proportionally with
steering latency, and commitment saturates at 100% by ~900 ms rather than switching at a threshold.
The hypothesis as written — that there is a critical latency below which steering becomes reliable
and above which it fails — is **falsified by this data**. The honest restatement is weaker and
duller: *steering latency and free-run length trade off continuously, with no special point.*

**What replaced it, and was not predicted.** The injector's politeness window is a second governing
parameter of comparable strength that the hypothesis ignored entirely. `quiet_frames_to_start=6`
forces 480 ms of caller silence before forcing may begin, *regardless of how fast the brain is* —
which is why the first (invalid) sweep looked flat, and why making the brain faster than ~480 ms
bought nothing until this parameter moved. Latency and politeness are additive contributors to
free-run, and the politeness window was the binding one at the fast end.

**Combined effect on the proxy, best vs July-equivalent configuration:**

| configuration | free-run tokens | committed |
|---|---:|---:|
| q=6, 1300 ms steering (≈ July's Gemini loop) | 11.08 | 100% |
| q=1, natural local brain | **2.25** | **33.3%** |

A 4.9× reduction in self-chosen words spoken before guidance lands. **This improvement is not
real** — see the turn-taking validation below, which shows the same configuration is worse on every
metric that the July claim was actually made in. It is recorded because it is the number this work
would have shipped had the proxy not been checked.

### Turn-taking validation — the proxy win inverts

`eval/duplex/turntaking_ab.py` reruns the comparison on the July benchmark's own terms: the same 10
scenarios, the same Piper lessac caller voice, the same `RMS_USER`/`RMS_AGENT` energy thresholds,
the same `CALLER_GAP_S`/`BARGE_AFTER_S` scheduling, scored by the same `turntaking.py`.

| arm | takeover | overlap | handoff p50 | handoff p95 | backchannels/call |
|---|---:|---:|---:|---:|---:|
| July baseline (`eval/bench/RESULTS.md`) | 0.24 | 0.234 | 240 ms | 3,248 ms | 0.4 |
| `julyish` — q=6, 1300 ms brain | **0.43** | **0.232** | **372 ms** | **938 ms** | 0.20 |
| `mid` — q=4, natural brain | 0.69 | 0.368 | 1,756 ms | 3,602 ms | 1.20 |
| `fast` — q=1, natural brain | 0.69 | 0.328 | 3,084 ms | 4,914 ms | 1.10 |

**The slowest, most polite arm is the best on every metric.** The `fast` configuration — the one
that cut free-run tokens 4.9× — has 59% more takeovers, 41% more overlap, and a handoff p50 **8×
worse** than the arm it was meant to improve on. `mid` is no better. Latency was not the binding
constraint on duplex control; `quiet_frames_to_start` was, and it was protective. Shrinking the
politeness window lets the injector start forcing while the caller is still talking, which produces
exactly the floor-grabbing that got the duplex core benched in 0016 — and then wrecks handoff too,
because an agent that interrupts has no clean turn boundary to respond at.

The `julyish` arm is a fair but inexact reproduction of the July baseline (takeover 0.43 vs 0.24,
handoff p50 372 ms vs 240 ms) — it uses Gemma steering rather than Gemini, so content and phrase
lengths differ. Overlap lands at 0.232 against July's 0.234, which suggests the harness reproduces
the baseline's acoustic character even where content differs. Treat it as the internal control; the
across-arm comparison is the valid one.

**Consequence for this whole direction:** the sub-1s duplex architecture this document set out to
build is not supported. The best-measured duplex configuration remains roughly the one the
repository already had in July, and it is reached by keeping the politeness window wide — which
makes steering-loop speed largely irrelevant to the metric that matters.

**GPU contention, also unpredicted.** `FastBrain` measured 279 ms standalone but 286–541 ms with
Moshi stepping concurrently — both compete for the same Metal device. Steering latency on a laptop
is therefore not a free parameter: the duplex core taxes it. Any budget that assumes the standalone
number is wrong by up to 2×.

### Limits of this evidence

n=12 turns per arm on one machine, one duplex model, one steering model, synthetic caller audio.
`committed_rate` is visibly noisy (66.7% at q=6 vs 91.7% at q=10 breaks monotonicity), so the
per-arm ordering is not trustworthy at that resolution even though the endpoints separate clearly.
No human listened to any of it — `free_run_tokens` and `committed_rate` are proxies for
"does it ramble," not measurements of naturalness. `turntaking.py`'s takeover/overlap metrics were
not wired into this harness and should be, since they are the metrics the July baseline used.

An earlier version of this sweep produced a much more dramatic result (0.00 free-run tokens at
170 ms) that **did not reproduce**. Three defects caused it: arms shared one `LmGen` so state leaked
forward and eventually overran `max_steps`; `delay_ms` can only *add* latency, so nominal arms below
the brain's natural speed were secretly the same arm; and the striking number came from the arm that
happened to run first on fresh state. The corrected harness resets per arm and reports actual
measured steer latency next to the nominal value. The discarded result is recorded here because it
was the one worth believing and it was wrong.

## The experiment

Fixed: Moshi q4 on this M5, one scenario set, one audio sampler temperature, one injector
configuration. Swept: **steering latency only**, via `FastBrain(delay_ms=…)`, which generates at
full speed and then waits — so the model, the phrasing and the content are identical across arms
and latency is the sole independent variable.

Arms: **170, 300, 600, 900, 1300 ms** (the last reproducing July's Gemini loop).

Dependent variables, all from harnesses that already exist:

| metric | source | reads as |
|---|---|---|
| takeover rate | `turntaking.py` | agent grabbed the floor mid-utterance |
| handoff p50 / p95 | `turntaking.py` | perceived response latency |
| overlap ratio | `turntaking.py` | fraction of caller frames talked over |
| `dropped_stale` | `injector.py` counter | guidance too late to speak |
| `cancelled_by_barge_in` | `injector.py` counter | guidance killed by the caller |
| `injected` | `injector.py` counter | guidance actually spoken |

**Prediction (falsifiable), made before the run and NOT borne out:** `dropped_stale` and takeover rate rise sharply somewhere between 300
and 900 ms, with a knee rather than a linear ramp, because below ~one clause of free-run the model
has not yet committed to its own content. **Falsified if** the curves are linear, flat, or the knee
sits outside the swept range.

**A latency win that raises takeover rate is a failed result**, per the same standard
`RESEARCH_DIRECTION.md` sets for the cascade work. Speed that makes the agent ruder is not progress.

## Honest novelty boundary

Most of the parts are prior art and should be described as such:

- **Full-duplex speech models**: Moshi (Kyutai), PersonaPlex. Not ours.
- **Text-stream injection**: Kyutai's own `on_text_hook` forcing mechanism; `injector.py` has used
  it since Phase 2.
- **Asynchronous augmentation of a duplex model**: MoshiRAG demonstrated the pattern.
- **KV/prefix caching**: standard practice, supported directly by `mlx_lm`.
- **Speculative and tiered execution**: well established outside voice.

Assembling known parts faster is engineering, not a contribution. The only thing here that would be
worth writing up is the **relationship**: that duplex steerability is governed by steering-loop
latency, that the governing quantity is free-run frames rather than milliseconds (making it
predictable from any model's frame rate), and that the threshold is empirically locatable and
already crossable on a laptop with a KV-cached 1B model. That claim is falsifiable, cheap for others
to replicate, and — if the knee exists — explains a decision the field has repeatedly made in the
other direction, including by this repository in 0016.

If the sweep shows no knee, the honest write-up is a negative result: steering latency does not
govern duplex control, and Moshi's eagerness must be attributed elsewhere.

## Scope boundary

This is a localhost latency PoC. The compliance layer that governs the production Aira path —
grounded fact IDs, forbidden-claim policy, consent and opt-out gating — is deliberately **not** part
of this configuration, and 0030's finding stands: there is no deterministic runtime gate on
forbidden financial claims, so nothing here may be pointed at a real caller. A duplex PoC that
speaks freely is a legitimate instrument for measuring turn-taking; it is not a product, and the
`response_problem()` gap must be closed before any of this touches a phone number.
