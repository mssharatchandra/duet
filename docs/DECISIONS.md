# DECISIONS.md — Duet engineering journal

Every non-trivial choice gets a dated entry: what was decided, the alternatives, and why.
Running project spend is tracked at the bottom. This file is a deliverable, not an afterthought.

---

## 0001 — 2026-07-05 — Repo scaffold, license, structure

**Decided:** Public repo `duet`, Apache-2.0, structure `/agent`, `/eval`, `/infra`, `/web-demo`, `/docs`.

**Why Apache 2.0:** matches Sesame CSM's license, is the most adoption-friendly choice for a project whose explicit goal is that other companies (Bolna, Giga-style teams) integrate it, and includes an express patent grant — which MIT lacks and which matters for corporate adopters.

**Name:** keeping **Duet** as the working name. Alternatives considered, for the record: **Sidetone** (the telephony term for hearing your own voice while speaking — literally what full-duplex means), **Crosstalk**, and **Barge** (from "barge-in," the industry term for user interruption). Sidetone is the strongest alternative if Duet collides with an existing product later. Not blocking on this.

---

## 0002 — 2026-07-05 — Open-source stack lock + license verification

**Decided:** adopt the mandated OSS-first stack. Licenses verified via the GitHub API on 2026-07-05 (the brief was right to ask — two components turned out to be dead):

| Component | Role | License (verified) | Notes |
|---|---|---|---|
| Langfuse | LLM tracing/cost per call | `NOASSERTION` on GitHub — core is **MIT**, `/ee` folders are commercial | Self-hosting the OSS core is explicitly permitted; we use no `/ee` features |
| LiveKit OSS | WebRTC SFU | Apache-2.0 | Self-hosted server, not LiveKit Cloud |
| Prometheus | Metrics | Apache-2.0 | |
| Grafana | Dashboards + alerting | **AGPL-3.0** | Fine: AGPL obligations trigger on modification+network service; we run it unmodified as an internal tool. Documented so adopters know. |
| Loki | Logs | AGPL-3.0 | Same reasoning |
| k6 | Load testing | AGPL-3.0 | Dev-time tool only, never shipped |
| faster-whisper | Baseline ASR | MIT | |
| Piper | Baseline TTS | ⚠️ `rhasspy/piper` is **archived**; successor `OHF-Voice/piper1-gpl` is **GPL-3.0** | Acceptable: invoked as a separate process in the *eval baseline only* — never linked into Duet's Apache code. Fallback: Kokoro TTS (Apache-2.0). |
| Caddy | Reverse proxy/TLS | Apache-2.0 | |
| Postgres | DB (leads, audit log, metrics) | PostgreSQL License | |
| Listmonk | (future) mailing list | AGPL-3.0 | Not deployed in v1 |
| Moshi (Kyutai) | candidate duplex core | Apache-2.0 (code); weights CC-BY-4.0 | See 0003 |
| CSM-1B (Sesame) | candidate duplex core | Apache-2.0 | See 0003 |

**⚠️ Deviation flag — MinIO:** `minio/minio` is **archived on GitHub**. MinIO effectively ended its open-source community edition in 2025 (features stripped, then the repo frozen). Adopting an archived dependency in a project pitched on "no vendor lock-in" would be self-defeating. **Proposal:** for v1 demo scale, store recordings on a plain Docker volume with paths + retention tracked in Postgres; if/when S3-compatible storage is genuinely needed (Phase 4), use **SeaweedFS (Apache-2.0)** or **Garage (AGPL-3.0)** instead. Flagged here per the brief before switching. **Update 2026-07-05: ✅ ACCEPTED by user** — Docker volume for v1, SeaweedFS if S3-compatible storage is genuinely needed in Phase 4. *(Also noted: Coqui TTS the company shut down in 2024; its code lives on as a community fork under MPL-2.0, but Piper/Kokoro are the healthier baseline choices.)*

**Alternatives considered:** paid SaaS at each layer (Datadog, LiveKit Cloud, S3, Mailchimp) — rejected per cost guardrails and because self-hostability *is the pitch*.

---

## 0003 — 2026-07-05 — ⚠️ ARCHITECTURAL FORK (awaiting user decision): the duplex core — CSM vs. Moshi

This is the load-bearing decision of the whole project, and the brief's default ("lean CSM") hides a trap that has to be surfaced honestly.

**The trap: CSM-1B is not a full-duplex model.** Sesame's open-sourced CSM-1B is a *conversational speech generation* model — a context-aware TTS. It takes conversation history (text + audio) and produces expressive speech. It has **no listening path while speaking**; it cannot backchannel or detect interruptions natively. Sesame's famous demo wraps CSM in additional (closed) orchestration. Building "full-duplex Duet" on CSM alone means we'd be hand-engineering duplex behavior (VAD, streaming ASR, barge-in logic) around a TTS — i.e., building a *better cascade*, which is exactly the architecture this project exists to leapfrog.

**Moshi (Kyutai) is the only production-grade open model that is natively full-duplex.** It models **two audio streams simultaneously** — the user's and its own — as parallel token streams over the Mimi streaming codec (12.5 Hz frames, ~80ms), plus an "inner monologue" text stream. There are no turns in the architecture at all: interruption handling and backchanneling are emergent, not engineered. Theoretical latency ~160-200ms. Apache-2.0 code, CC-BY-4.0 weights, and — critically for our cost guardrails — Kyutai ships an official **MLX backend (`moshi_mlx`)** with 4/8-bit quantization that runs on Apple Silicon, and an official `moshi-rag` example of exactly the async-augmentation pattern Phase 2 requires.

**Trade-offs, honestly stated:**

| | Moshi | CSM-1B |
|---|---|---|
| Natively full-duplex | ✅ the whole point | ❌ generation-only |
| Fits M-series 16GB via MLX | ✅ official backend, ~4-8GB quantized | ✅ community MLX ports |
| Voice quality/expressiveness | Decent, slightly robotic | ✅ excellent |
| Steerability/intelligence | ⚠️ weak — rambles, hard to keep on-script (this is *why* Phase 2's async reasoning layer exists) | N/A (intelligence comes from whatever LLM you pair it with) |
| Persona/voice control | Limited | ✅ strong |
| Ecosystem fit | `moshi-rag` = our Phase 2 pattern, first-party | No duplex tooling |

**Recommendation:** **Moshi as the duplex core.** The concrete reason the brief asked for: CSM cannot do the one thing the project is named after. CSM remains on the bench for a possible future role (higher-quality voice for the *baseline*, or a "CSM-cascade-plus" middle configuration in the benchmark).

**Also evaluated:** Kyutai's *Unmute* (2025) — a cascaded-but-smart stack (streaming STT + semantic VAD + streaming TTS) that fakes duplex well. Rejected as the core (it's still a cascade) but it's a strong candidate for making our Phase 3 *baseline* state-of-the-art-fair rather than a strawman.

**Status: ✅ ACCEPTED by user, 2026-07-05.** Moshi is the duplex core. Cost impact: none (runs locally on the Mac).

---

## 0004 — 2026-07-05 — Phase 1 built: implementation choices + measured results

**Toolchain:** system Python was 3.9 (too old for MLX stack) → adopted **uv** with a managed
Python 3.12 and a per-package venv in `/agent`. Free, reproducible, and `uv run duet-local`
gives the brief's "one command" demo.

**Hardware (actual, verified):** Apple **M5, 24 GB** unified memory — better than the brief's
assumed 16 GB Air. 4-bit weights chosen as default anyway so the project stays runnable on
16 GB machines; `-q 8` / `--bf16` exist for quality experiments.

**Vendored an annotated loop instead of shelling out to `python -m moshi_mlx.local`:**
`agent/duet_agent/local_loop.py` is adapted from upstream (Kyutai, Apache-2.0, attributed in
the header) with three changes: heavy teaching annotation (it *is* Lesson 1), latency/memory
instrumentation printed on exit, and a `--headless N` benchmark mode that reuses the exact
live-mode `step_once()` — which later seeds the Phase 3 harness. Alternatives: use upstream
as a black box (fails the teaching goal), or write from scratch (risk without benefit).

**Measured results (M5, q4, 300-frame headless run, 2026-07-05):**

| Metric | Value | Meaning |
|---|---|---|
| Model load + warmup | 1.5-2.3 s | cold start to conversational |
| Steady-state step p50 / p95 / max | **48.5 / 51.0 / 81.1 ms** | vs the 80 ms/frame real-time budget → **+29 ms headroom at p95** |
| First-steps max | ~540 ms | one-off Metal kernel compilation; absorbed by warmup frames in live mode |
| Peak RSS / Metal memory | **4.6 / 5.2 GB** | brief asked to verify the ~8 GB estimate — actual is lower; fits 16 GB Macs comfortably |
| Emergent behavior check | fed 24 s of silence → model said "Hey what's up?" | turn-taking initiative with zero orchestration code |

**Known limitation (accepted for Phase 1):** the raw `sounddevice` path has **no acoustic echo
cancellation** — on open speakers Moshi hears its own voice and can react to itself. Mitigation
now: headphones. Real fix arrives naturally in Phase 4: browser WebRTC (LiveKit) does AEC on
the client side for free. Not building AEC ourselves — that would be reinventing what the
transport layer already provides.

**Spend:** still $0.00 (≈5 GB of bandwidth).

---

## 0005 — 2026-07-05 — Reasoning model: discovery, measurement, choice

**Key handling:** user-provided Gemini key lives in local `.env` (gitignored, chmod 600) and as a
GitHub Actions secret for the eval gate. ⚠️ The key was shared via screenshot and AI Studio shows
an older key on the account flagged as publicly exposed — recommended rotating that older key;
treat this one as dev-tier and rotate before any public launch.

**Don't trust stale model names:** queried the live API instead of hardcoding. Current stable
flash family includes `gemini-3.5-flash` and `gemini-3.1-flash-lite` (the "2.5" generation the
original brief era assumed is two generations old).

**Measured round-trip on a representative SDR objection prompt (2026-07-05):**

| Model / config | Latency |
|---|---|
| gemini-3.5-flash (default = thinking on) | 5,069 ms — unusable for voice |
| gemini-3.5-flash, thinkingBudget 0 | 1,748 ms |
| **gemini-3.1-flash-lite (chosen default)** | **~1,000-1,300 ms** |

**Decision:** default `gemini-3.1-flash-lite`, overridable via `REASONING_MODEL` env var; thinking
disabled automatically for non-lite models. Rationale: in the async-augmentation pattern the brain's
latency is masked by Moshi's natural backfill, but shorter masking = less filler; quality is gated
by the eval (0006), which lite passes. Cost estimates in `reasoning.py` `PRICE_PER_M` are marked
as estimates — re-verify before publishing Phase 3 cost benchmarks; dev usage rides the free tier.

---

## 0006 — 2026-07-05 — Phase 2 architecture: text-stream injection + CI/eval design

**Injection mechanism:** `LmGen(on_text_hook=…)` — the hook receives each frame's sampled text
token *after* text sampling, *before* the depformer generates that frame's audio conditioned on it.
Overwriting the token (in-place `text_tokens[:] = …`) makes Moshi speak the forced word in its own
voice. This is Kyutai's own first-party forcing mechanism (their TTS engine, `models/tts.py:607`,
does exactly this), so we're on supported ground, not a hack. Alternatives considered: prompt-level
conditioning (no runtime control), audio-token splicing (breaks prosody, fights the depformer).

**The crux (async slowness / interruptions), as three injector rules:** (1) injection waits for a
pad-token word boundary AND ~0.5 s of user quiet — slow guidance sounds like a person taking a
beat, because Moshi free-runs meanwhile; (2) user barge-in during forcing **drops** the rest of the
script (never resumes a stale pitch); (3) guidance older than 8 s is discarded unspoken. The user's
audio path never gates on any of this — that would rebuild a cascade.

**ASR position:** faster-whisper (optional dep, `--live` mode only) transcribes the *lead* for the
brain. It feeds the brain, not the mouth: the 80 ms loop never waits on it.

**End-to-end verification (scripted mode, real Moshi + real Gemini, 2026-07-05):** 4/4 talking
points injected into Moshi's speech; brain latency avg 1,281 ms fully masked; objections classified
correctly (`status_quo`, `price`); lead scored 100/100 by the deterministic BANT rubric; call cost
$0.00035 at list price. User waived the live-mic checkpoint (couldn't run it); scripted mode is the
stand-in until the Phase 4 web demo exists.

**CI (every push/PR):** ruff lint · unit tests on ubuntu (proves brain modules are stdlib-pure) and
macos Apple-Silicon (full MLX stack + import smoke) · live reasoning golden eval on push with a
**≥90% gate** (12 scenarios × ~3.4 checks: intent, objection classification, fact grounding, two
anti-hallucination canaries, brevity, BANT signals). First run: **92.7%**, failures logged and left
honest rather than widening the checks. Deliberately NOT in CI: the 4.9 GB Moshi weights — the
scripted e2e (`duet-sdr`, VERDICT: PASS) is the local pre-push gate instead; pulling 5 GB per
commit is slow, flaky, and wasteful. Revisit with a weight cache if it ever bites us.
---

## 0007 — 2026-07-05 — Phase 3: benchmark results, infra pivot, measurement decisions

**Docker pivot:** this Mac has no Docker, no Homebrew, and no admin rights, so the observability
stack cannot run locally this phase. Decision: author the full stack in `infra/` (pinned upstream
`langfuse-compose.yml` + our `observability-compose.yml` with Grafana/Prometheus/Loki/duet-postgres,
dashboards auto-provisioned, Langfuse headlessly provisioned via `LANGFUSE_INIT_*`) and **verify it
in CI** (`.github/workflows/infra.yml`: stack up → Langfuse health + ingestion 207 → Grafana
datasource provisioned → CallStore Postgres write). All local telemetry is fail-silent; benchmark
truth lives in JSONL regardless. Local dashboards arrive when the user installs OrbStack/Docker
Desktop; production dashboards arrive on the Phase 4 VPS.

**Update 2026-07-05 (local):** the stack now ALSO runs locally without admin rights — Colima
v0.10 + Lima + docker CLI installed userspace (`~/.local/bin`), VM via Apple
Virtualization.framework (`colima start --vm-type vz --cpu 4 --memory 6`). All 10 containers
healthy; 22 calls in Postgres; Langfuse showing per-turn generations; Grafana dashboard live.
After a reboot run `colima start` before `docker compose`. No password was ever needed — noted
so future "needs Docker Desktop/admin" assumptions get challenged.

**Measurement decisions:** app metrics go to Postgres (not Prometheus) because benchmark processes
are short-lived — pull-based scraping needs a long-running server, which exists in Phase 4.
Takeover/backchannel/handoff/overlap definitions in `turntaking.py` (backchannel ≤0.6 s). Cascade
constants: `ENDPOINT_WAIT_S=0.7`, `BARGE_KILL_S=0.4`. GPU pricing declared: `GPU_USD_PER_HOUR=0.40`
(L4-class). Baseline TTS: piper-tts now ships arm64 wheels — no Kokoro fallback needed.
Ops lesson: multi-minute benchmarks on a laptop must run under `caffeinate` — the first attempt
died to system sleep (a 9,500 s "wall time" scenario and a stalled codec thread).

**Results (full table + honest reading: `eval/bench/RESULTS.md`):** Duet handoff p50 **240 ms** vs
cascade **1,880 ms** (~8×) and 0.4 backchannels/call vs 0 — but Duet takeover rate **0.24** vs 0.00,
overlap 0.234 vs 0.053, p95 tail worse (3.2 s vs 2.2 s). Published as-is, including the note that
the takeover metric is biased against Duet. Human Delta-4: not yet measured — clips + protocol
ready (`docs/BLIND_EVAL.md`), needs human raters only the user can recruit.

**Implication for Phase 4/5:** Duet's weak spots (eagerness, p95 tail) are tunable — audio-sampler
temperature, injection politeness windows — and the harness now exists to measure any such change.
That is the whole point of building the instrument first.
---

## 0008 — 2026-07-07 — Web demo + the audio-clarity investigation

**User report:** terminal demo speech unintelligible. **Root causes found by measurement, in order
of impact:** (1) resource contention — with the observability stack + a background weights download
running, model step p95 degraded from 50 ms to 335+ ms (ClickHouse alone at 72 % CPU; Docker VM and
download hashing did the rest), so the speaker buffer starved into stutter; (2) no echo cancellation
in the raw sounddevice path (Moshi heard itself on speakers); (3) zero playback buffering, so any
jitter was audible. On a quiet system q4 measures p50 47.7 / p95 50.0 ms — unchanged from Phase 1.

**Fixes shipped:** browser demo (`web-demo/`, aiohttp + WebSocket + AudioWorklets @ 24 kHz —
one binary frame = one 80 ms Mimi frame, no resampling anywhere) with getUserMedia echo
cancellation/noise suppression, a 320 ms jitter buffer that re-arms on underrun, server-side
mic-backlog dropping to stay live, live caller transcript (faster-whisper), Moshi's words as
spoken, brain-injection chips, and step-latency stats on the page.

**q4 vs q8 decision (measured, quiet system, M5):** q4 p50 47.7 / p95 50.0 ms (+30 ms headroom) vs
q8 p50 74.3 / p95 91.0 ms (−11 ms at p95, 8.3 GB Metal). **q4 stays the default** — q8's marginal
voice quality loses to the stutter its missed deadlines cause; `-q 8` remains for faster hardware.

**Ops lessons:** real-time inference and an analytics warehouse don't share a laptop — the demo
script now says to stop the Langfuse stack before voice demos (production separates these machines
anyway). And every long-running background job on a Mac gets `caffeinate`, no exceptions — sleep
killed both a benchmark run and this weights download.
---

## 0009 — 2026-07-07 — Humanization round: the 16 kHz ASR bug, paced injection, temp knob

**STT was inaccurate for a hard reason, not a model reason:** faster-whisper assumes **16 kHz**
for raw numpy input; every live path fed it our pipeline-native **24 kHz** audio unresampled, so
it heard everything slowed 1.5×. Fixed via shared `duet_agent/asr_util.to_whisper_rate()` in the
web server, live SDR mode, and the benchmark cascade (whose measured ASR latencies were on
wrong-rate audio — rerun before publishing cascade numbers anywhere new). ASR model default
upgraded base.en → **small.en** (env `ASR_MODEL`), still CPU-side and off the hot path.
Lesson generalized: one-sample-rate-end-to-end failed silently at the single boundary we forgot.

**"In a hurry" diagnosed:** forced injection fed content tokens back-to-back at 12.5 tokens/s with
none of the pad-token breaths natural Moshi speech interleaves. `TextInjector(pace_pads=2)` now
inserts 2 pads per token in live/demo paths (≈4 tokens/s). Cost: injections occupy ~3× more
frames, so barge-in cancels them more often — correct behavior, verified in scripted mode.

**Voice character knob:** `--temp` exposed on duet-local and the web server (audio sampler;
0.8 default, 0.6 = cleaner/flatter). Robotic timbre itself remains a model ceiling (1B decoder,
streaming codec bitrate, q4) — documented honestly in the blog §7.
---

## 0010 — 2026-07-07 — ⚠️ PROPOSED (awaiting decision): ecosystem integration strategy + Fish Audio verdict

**Organizing principle: integrate by latency class.** Duet has three tiers with different budgets, and
every integration question resolves cleanly once you ask which tier it touches.

| Tier | Budget | External calls? |
|---|---|---|
| A — the mouth (Moshi loop) | 80 ms, hard | **Never.** No API, no MCP, no network. A network call here is architecturally forbidden; it recreates the cascade we exist to replace. |
| B — the brain (ReasoningLayer) | ~1 s, async, maskable | **Yes — MCP belongs here.** |
| C — transport/platform | connection-time | **Yes — this is where deployability lives.** |

**Tier B proposal — MCP tools in the brain.** `ReasoningLayer` already returns structured JSON; adding
MCP tool-calling lets the SDR agent *do* things instead of talking about them: check calendar
availability, book the demo, look up/create the CRM record, log call outcome. Demo impact is the
difference between "shall we book a demo?" and a real calendar invite landing during the call. Cost:
none beyond token use; MCP servers for calendar/CRM are off-the-shelf. Risk: tool latency stacks onto
brain latency — mitigated because injection etiquette already tolerates seconds and Moshi backfills.

**Tier C proposal, ranked by adoption leverage:**

1. **OpenAI Realtime API-compatible WebSocket shim** (`web-demo/realtime_shim.py`). Makes the README's
   "drop-in" claim literal: any existing Realtime client points at Duet by changing a URL. Every major
   framework already ships a Realtime client, so this is one adapter that unlocks all of them.
   Honest wrinkle worth documenting publicly: Realtime's event model (`response.create` / `response.done`)
   **assumes turns**, so a genuinely full-duplex backend has to synthesize turn events from its
   turn-taking detector — even the modern protocols encode the assumption Duet removes.
2. **LiveKit Agents plugin** (Apache-2.0, 11.6k★, actively maintained). Native distribution into the
   biggest realtime-agent ecosystem, and SIP telephony arrives free — which is exactly the outbound-sales
   thesis. Phase 4 already picked LiveKit OSS for transport; the plugin is the ecosystem-native form.
3. **Pipecat service wrapper** (BSD-2, 13.8k★). The other large framework; a `DuetService` is a fast
   follow once (1) exists.
4. **Duet-Bench as an MCP server** (differentiated, lower priority): expose the turn-taking harness so
   any team can measure *their own* stack's takeover rate/handoff latency. The harness may prove more
   adoptable than our model layer.

**❌ Fish Audio (fishaudio/fish-speech, 31.8k★) — rejected as a dependency.** License verified
2026-07-07: **"FISH AUDIO RESEARCH LICENSE AGREEMENT"** — free for research/non-commercial only;
**any commercial use requires a separate license from Fish Audio**. Duet is Apache-2.0 and pitched
explicitly at companies adopting it; a non-commercial core dependency destroys that story. Same class
of finding as MinIO-archived (0002) and Piper-GPL (0002). *(Note: `fish-audio-python` is Apache-2.0
but it's only a client for their paid hosted API — not self-hostable, so it fails the OSS-first rule.)*

**Also architecturally weaker than it looks:** fish-speech is a TTS — generation-only, like CSM (0003).
It cannot replace the duplex core. Driving an external TTS from Moshi's inner-monologue text stream is
possible, but the text stream carries *words only* — you'd discard the prosody, backchannels and
hesitations that live in Moshi's audio stream, re-add TTS time-to-first-byte, and reintroduce
barge-in-kill. That trade (better timbre, worse timing) is precisely the frontier tension in blog §7,
and it converts Duet into a smarter Unmute rather than a full-duplex system.

**Narrow exceptions where Fish Audio would be legitimate:** (a) a *stronger baseline voice* in the eval
(research use, clearly labeled, never linked into shipped code); (b) a user-supplied "voice tier" that
adopters wire up under their own commercial license.

**Cheaper fix for the actual voice complaint:** our timbre is partly a *laptop* constraint — q4 was
chosen because q8 misses the 80 ms budget on an M5 (0008). On the Phase 4 deployment GPU (L4-class,
already budgeted at ~$0.40/hr) **bf16 weights fit the budget comfortably** and sound better than q4 or
q8. Recommend measuring this on the first GPU deploy before considering any TTS-swap architecture.

**Recommendation:** do (1) Realtime shim → (2) LiveKit Agents plugin → Tier-B MCP tools, alongside
Phase 4. Skip Fish Audio. All of the above is $0 additional spend.
---

## 0011 — 2026-07-07 — Goal reframe: learning-first, and what that changes

**User reframed the objective:** company adoption (Bolna/Giga) is no longer the driver — the goal is
personal mastery of voice AI. Recorded because it invalidates part of 0010's reasoning.

**What changes:** the Fish Audio rejection in 0010 was *entirely* about its commercial restriction.
The Fish Audio Research License permits research/non-commercial use freely, so for learning it is
fully usable. Standing advice anyway: prefer MIT/Apache at equal quality (Chatterbox, 25.8k★, MIT,
sub-200 ms) so a learning project never needs a rewrite to become something real.

**What does NOT change:** fish-speech is still a TTS, not a duplex model — it cannot replace the core
(0003, 0010). And 0010's latency-class rule (nothing external in the 80 ms mouth; MCP belongs in the
async brain) is architecture, not licensing, so it stands regardless of goal.

**Also unchanged:** Apache-2.0 for this repo, the honest benchmark, and the no-unmeasured-claims rule.
Those serve a learner at least as well as they served an adopter.

**New artifact:** `docs/BUILD_WORLDCLASS.md` — learner roadmap: verified 2026 open stack, six
projects (voice tier → semantic turn detection → cloning → speech-native LLM → train a small head →
telephony), reading list, and measurable definitions of "world-class". Next concrete target named
there: takeover rate 0.24 → <0.10 while holding handoff p50 <300 ms.
---

## 0012 — 2026-07-07 — ASR eval: two of our own claims, disproved

Built `eval/asr/run_asr_eval.py` — WER + real-time-factor over the 30 benchmark utterances
(Piper-synthesized, scenario text as ground truth). Turning "the transcription isn't accurate"
into a number immediately falsified two things this journal previously asserted.

| config | WER | RTF |
|---|---|---|
| small.en, **fed 24 kHz as 16 kHz (the 0009 bug, reproduced as a control)** | **2.3%** | 0.31x |
| tiny.en | 5.3% | 0.04x |
| **base.en** | **2.3%** | **0.09x** |
| small.en | 2.7% | 0.33x |
| distil-large-v3 | 3.4% | 1.64x (slower than real time on CPU — unusable live) |

**Correction 1 — the sample-rate bug was not the cause of bad transcripts.** 0009 called it "the
root cause"; on this data it costs **nothing** (2.3% either way). Whisper is evidently robust to a
1.5x slowdown on clean speech. The fix is still correct (feeding a model the rate it expects is not
optional, and the penalty on noisy/accented speech is likely real) — but the *claim* was unearned
and is withdrawn.

**Correction 2 — the base.en → small.en "upgrade" was unjustified.** small.en measured *worse*
(2.7% vs 2.3%) at 3.7x the compute. Default reverted to `base.en`; `ASR_MODEL` still overrides.
Bigger was not better twice over: distil-large-v3 was worst of the three usable models.

**The finding that matters most: this eval is not on-distribution.** If ASR sits at ~2.3% on clean
speech regardless of model, then the user's live experience of inaccurate transcription is *not*
explained by model choice — so the cause is elsewhere in the live path (mic quality, VAD
segmentation chopping utterances, self-hearing, buffering). The eval's real value here was telling
us **where not to look**. The worst remaining case is even a TTS artifact ("Ah shame" synthesized as
"Aahshane"), i.e. the harness's own voice, not the recognizer.

**Next, and it needs the user:** capture real microphone audio + corrected transcripts from a live
web-demo session to build an on-distribution ASR eval set. Synthetic speech cannot settle
base.en vs small.en for a real room; recorded speech can.
---

## 0013 — 2026-08-01 — The augmented ASR eval discriminates — and reverses 0012

0012 ended with an open question: our ASR eval was too flat (every model ~2.3% WER on clean
synthetic speech) to choose between candidates. A subagent built `eval/asr/augment.py` (seeded
noise / reverb / speed / gain degradations) and an `--augment` matrix mode. The question is
answered: **degrading the audio does separate the candidates, decisively.**

| model | clean | snr20 | snr10 | snr5 | reverb | fast | slow | max RTF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base.en (0012's default) | 4.2% | 5.7% | 7.6% | **14.1%** | 4.2% | 4.9% | 4.2% | 0.30x |
| small.en | 3.0% | 3.0% | 4.9% | 8.7% | 2.7% | 3.0% | 3.0% | **1.42x** |
| mlx-whisper-large-v3-turbo | 2.3% | 1.5% | 1.9% | 3.4% | 2.7% | 1.9% | 2.7% | 0.87x |
| **parakeet-tdt-0.6b-v3** | **1.9%** | **1.5%** | 2.7% | **2.7%** | **1.9%** | **1.9%** | **1.5%** | **0.08x** |

**Correction of a correction.** 0012 reverted the default to `base.en` because small.en showed no
benefit on clean speech at 3.7x the compute. Under noise that is flatly wrong — base.en collapses
to 14.1% WER at SNR5 while small.en holds 8.7%, and small.en wins in *every* condition. Default
moved to **small.en**.

**The lesson, which is the valuable part:** I chose a default from an eval that could not
discriminate, and reported it as a measured decision. An eval that cannot separate candidates is
not evidence for a choice — it is the *absence* of evidence. "No measurable difference, so take the
cheaper one" was a defensible cost argument dressed up as a quality finding. Dianne Penn's question
— *is the eval on distribution?* — was the right one, and clean TTS speech was not.

**Why not parakeet as the default, despite winning outright:** two unresolved risks. (1)
`parakeet-mlx`'s public `transcribe()` shells out to `ffmpeg`, absent on this machine (no Homebrew);
the agent bypassed it via the model's own `get_logmel()`/`generate()`, so we depend on a private
path rather than the supported API. (2) Its RTF was measured with **Moshi not running** — parakeet
executes on MLX/Metal, the same GPU as the duplex core, so its 0.08x headroom is untested under
exactly the contention that has bitten this project twice (0008, and again during the user's live
demo where an eval at ~300% CPU pushed model step p95 to 402 ms against an 80 ms budget). Marked as
the likely upgrade pending a with-Moshi contention test.

**Bonus finding against my own code:** Piper synthesis is **not** deterministic across process runs,
contradicting the "deterministic" claim in `run_asr_eval.py`'s original header. Cross-run WER
comparisons were therefore never strictly apples-to-apples; the agent's single-process combined run
(all models on byte-identical audio) is the trustworthy one, and is what the table above reports.

**Still open:** the real-microphone eval. Session capture now works end to end in the web demo and the
first real utterance is recorded, but one utterance is not a benchmark.
---

## 0014 — 2026-08-01 — Hermes Voice v0: canonical scheduler, self-grade default, explicit remote grade

**Status:** Accepted and implemented locally. Human voice evaluation remains open.

### Context

The first differentiated product slice is spoken recall over `hermes-brain`, not another generic
assistant. Two constraints shape the boundary: Hermes owns the approved learning artifacts and
review schedule, and its default privacy is `private`. Duet must not fork the scheduler or silently
upload private learning material merely because its existing SDR brain uses Gemini.

### Decision

Duet reads only Hermes runs with `approved` or `published` status, selects the oldest due run using
the same `review.completed.data.due_at` event contract, and parses its numbered `recall.md` questions.
The browser runs a deterministic question/score state machine. Local human self-grading is the
default. `--hermes-remote-grading` is an explicit alternative that sends the reviewed article and
spoken answers to Gemini and discloses that fact in the UI.

A completed score is never written automatically. The learner presses **Record this review in
Hermes**; Duet calls Hermes' canonical `python3 scripts/brain.py review` command, then reads the
event log back and verifies the appended score. Partial answers count as incorrect because Hermes'
current review contract accepts integer `correct` and `total` values.

### Options considered

| Option | Complexity | Privacy | Scheduler drift | Assessment |
|---|---:|---:|---:|---|
| Reimplement cards + schedule in Duet | medium | local | high | Rejected: creates a second brain |
| Automatic Gemini grading by default | low | private data leaves Mac | low | Rejected: contradicts local-first framing |
| Local self-grade + explicit Gemini opt-in | medium | local by default | low | **Chosen** |
| Add a local grading LLM now | high | local | low | Deferred until measured self-grade friction justifies it |

### Consequences

- A useful vertical slice works without a new model or a schema change in the dirty Hermes worktree.
- Hermes remains the durable source of truth and computes the next interval itself.
- Automatic grading is available but cannot be mistaken for a private path.
- Self-grading adds a button press after each spoken answer; whether that harms the experience is
  an open human-eval question, not a hidden trade-off.
- The current integration loads the reviewed article for remote grading; retrieval/chunking is
  unnecessary at today's document sizes but must be revisited before long corpora.

### Verification

- Ruff passed across `agent`, `web-demo`, and `eval`.
- Unit suite: **84 passed** (7 new Hermes/profile tests).
- No-model server started against the real sibling Hermes checkout; WebSocket emitted the due
  OAuth run with 7 questions, self-grading, and the local-first disclosure.
- Real-model timed-silence smoke: the complete first OAuth question appeared in Moshi's inner
  monologue and produced 85 non-silent audio frames. **Bad result preserved:** model-step p95 was
  **147.1 ms against the 80 ms budget** on the currently busy desktop. This was not a controlled
  benchmark and does not supersede the quiet-machine q4 result; it does prove the experience is
  presently vulnerable to ordinary desktop contention. The UI now shows missed-frame rate in red
  and emits a realtime-budget warning.
- Not verified yet: one full human spoken review, subjective audibility/prosody of long questions,
  or the final write button against the real Hermes event log (that remains user-triggered by design).

## 0015 — 2026-08-01 — Live ASR failure: speech was discarded before Whisper

**Trigger:** the first human Hermes Voice trial reported that essentially nothing spoken appeared
in the transcript. This is a release blocker, not a minor WER regression.

**Root cause 1 — fixed acoustic gate.** Live segmentation used a fixed RMS threshold of **0.015**.
In the two captured real-mic clips, median frame RMS measured **0.01329** and **0.00396**; the quieter
clip crossed the gate in only 5 of 14 frames. Most speech was therefore labeled silence or chopped
before Whisper received it. The model could not transcribe audio it never saw.

**Root cause 2 — startup coupling.** The WebSocket previously copied mic frames to ASR from inside
the Moshi model loop. Speech during model loading was silently lost. The WebSocket now tees frames
directly to the brain queue, independent of Moshi startup and realtime health.

**Recognition finding — default changed provisionally.** On the one human-corrected real clip,
ground truth “That's all,” `base.en` was exact while `small.en` produced “That's funny.” That single
utterance is not a benchmark, but it is the only on-distribution labeled evidence, so the browser
default moves **small.en → base.en provisionally**. This reverses 0013 only for the live browser;
the augmented synthetic matrix still favors small.en under noise. Collect at least 20 corrected
real utterances before making a durable model choice.

**Fix:** one shared adaptive segmenter now calibrates 480 ms of room tone, uses
`max(0.003, noise_floor × 1.8)`, accepts 160 ms short answers, and waits 640 ms of quiet to close.
An attempted onset pre-roll was rejected after replay showed that even 80–240 ms of preceding room
tone caused Whisper hallucinations on the short clip. The page now exposes calibration, live RMS,
adaptive threshold, speech detection, transcription latency, and empty/error results. Beam search
increased from 1 to 5 and previous-text conditioning remains off so one hallucination cannot poison
the next utterance.

**Verification:** 14 segmenter/capture tests pass, including quiet speech above a measured room
floor and constant-noise rejection. The full suite is **86 passed**. A realistic WebSocket replay
calibrated on the captured clip's actual room tone, detected the 1.12 s utterance, and returned the
verified “That's all.” with `base.en` in **1,284 ms** without Moshi and **1,368 ms** while q4 Moshi
loaded and ran concurrently. This verifies the repaired path, not general ASR quality. Accent,
long-answer, crosstalk, and real human simultaneous-Moshi accuracy remain unmeasured.

## 0016 — 2026-08-02 — Replace the default Moshi/Whisper demo with a guarded open voice cascade

**Status:** Accepted and implemented locally. Human conversational evaluation remains open.

### Context

The second live trial was worse than a missed transcript: Duet displayed long, confident sentences
the learner never spoke, including “Yeah. That's why it's so loud…” and repeated punctuation. It
then responded to those inventions. A voice product that fabricates user speech is unsafe to grade,
remember, or act on.

Replaying the five captured windows separated two failures. Silero found **0 ms of speech** in three
windows that Whisper had turned into text. It found 476 ms in the real “Hello” window, which
Parakeet transcribed exactly in 90 ms in the existing environment. A fifth window contained 380 ms
of apparent speech from speaker leakage; no recognizer can know from a mono waveform whether that
voice came from the user or Duet. The transport must enforce that boundary.

### Decision

The browser's default voice path is now a local half-duplex cascade:

`adaptive candidate window -> Silero VAD -> Parakeet TDT 0.6B via MLX -> reasoning -> Piper TTS`.

Microphone frames are discarded from synthesis start until 250 ms after a 450 ms playback-drain
period. Browser acoustic echo cancellation stays enabled, but correctness does not depend on it.
Moshi remains behind `--voice-stack moshi` as an experiment; it is no longer the default product
experience. Whisper remains a compatibility backend behind `--asr whisper:<model>` and is still
preceded by Silero.

The open voice runtime lives in `web-demo/.venv`. This isolation is required: `moshi-mlx==0.3.0`
requires `huggingface-hub<0.29`, while `parakeet-mlx>=0.5` requires `huggingface-hub>=0.30.2`.
Parakeet 0.5.2 also resolves an obsolete Python-incompatible Numba declaration, so the runtime pins
the working Python 3.12 pair, Numba 0.66 / llvmlite 0.48.

### Options considered

| Option | Assessment |
|---|---|
| Keep tuning faster-whisper | Rejected: a language-model decoder can still complete admitted noise into words; it does not solve self-playback |
| Sarvam Saaras/Bulbul | Strong future hosted option for Indian languages and code-mixing, but requires an API key and is not open model weights |
| Bolna | Useful open orchestration for provider-backed phone agents; adopting it would not itself fix acoustic ownership |
| Fish Speech | Capable TTS only, not ASR or orchestration; current weights use the Fish Audio Research License |
| Pipecat | Best future open orchestration candidate; deferred because replacing transport and Hermes session state simultaneously adds migration risk |
| Silero + Parakeet MLX + Piper in existing Duet transport | **Chosen:** local, measured on this M5, minimal migration, explicit acoustic boundary |

Piper is the stable TTS default. Kokoro generated 2.08 seconds of audio in 0.60 seconds, but the
current Torch/native combination exited with signal 138 during teardown; successful synthesis does
not make a crashing runtime shippable.

### Consequences

- Duet cannot be interrupted while it speaks. This is an intentional reliability trade-off for v1;
  barge-in returns only after echo ownership is measured and tested.
- Non-speech now produces no transcript instead of a plausible invention.
- ASR and TTS remain pluggable, so Sarvam or Pipecat can be evaluated without rewriting Hermes.
- The open runtime downloads local model weights but sends no audio to an ASR/TTS vendor.
- Capture remains opt-in and is still the source of on-distribution corrections.

### Verification

- Unit suite: **89 passed**; Ruff passed across the agent and web demo.
- Dedicated runtime resolved and loaded Silero, Parakeet MLX, and Piper on Apple M5.
- Captured failure replay: three Whisper hallucination windows rejected at 0 ms neural-VAD speech;
  real “Hello” accepted and transcribed exactly.
- Real WebSocket startup emitted the complete Hermes opening and 119 binary audio frames while ASR
  reported `paused: Duet is speaking`.
- End-to-end WebSocket replay after playback: room calibration -> 350 ms verified speech ->
  `Hello.` -> Hermes `tutor_answer`, with 868 ms first-real-utterance ASR latency in the clean runtime.

## 0017 — 2026-08-02 — Use Sarvam as the speech plane, not the interaction plane

**Status:** Accepted and implemented locally. Human conversational evaluation remains open.

### Context

The guarded local cascade stopped the catastrophic Whisper hallucinations, but the next live trial
still felt slow to release the user's turn and remained inaccurate. The product question was not
just whether Sarvam could improve ASR and TTS. It was whether adopting a hosted speech provider
would leave Duet with anything differentiated to build.

Tests on captured user audio showed a real ASR gain: Parakeet returned “Okay, top something,” while
Saaras v3 returned “Okay, talk something.” On a longer, less clear answer, Sarvam preserved roughly
the same words but punctuated them more usefully. A flushed short streaming recognition arrived
303 ms after flush. Bulbul v3 produced the first chunk of a 24 kHz streaming WAV in 496 ms, followed
by incremental audio chunks.

The same streaming test also exposed the provider boundary. During a real-time replay of a long
answer, Sarvam emitted `END_SPEECH` at a natural thinking pause and `START_SPEECH` when the learner
continued 200 ms later. Treating provider VAD as turn completion would make the tutor interrupt a
thoughtful speaker even when the transcription itself is correct.

### Decision

Sarvam is the default **speech plane** when `SARVAM_API_KEY` is present: one persistent Saaras v3
stream performs VAD and ASR, and Bulbul v3 streams tutor speech. Duet remains the **interaction
plane**. Its provider-independent `TurnAssembler` merges acoustic fragments, waits through a short
continuation grace period, and emits one conversational turn to Hermes. Existing playback ownership
still blocks microphone ingestion while Duet speaks. The Silero + Parakeet MLX + Piper path remains
the local fallback and can be selected explicitly.

### Options considered

| Option | Assessment |
|---|---|
| Let Sarvam own the complete agent | Rejected: good speech infrastructure does not provide Duet's Hermes grounding, memory, turn semantics, evaluation loop, or provider portability |
| Put a Duet control layer above Sarvam and local engines | **Chosen:** buys current Indian-English speech quality while keeping the differentiated interaction state under our control |
| Stay entirely local | Retained as the privacy/offline fallback; current captured evidence favors Sarvam on at least one real utterance |
| Enable true simultaneous listening immediately | Deferred: interruption requires measured echo ownership and cancellation, not only a streaming ASR socket |

### Consequences

- When the key is configured, user audio leaves the Mac for Sarvam ASR and tutor text leaves the Mac
  for Sarvam TTS. Hermes source articles and local grading state are not sent to Sarvam.
- The current advertised Sarvam pricing is INR 30/hour for speech-to-text and INR 30/10,000 TTS
  characters. Calls made during this validation cost only a small fraction of one rupee.
- A provider VAD event is evidence about acoustics, never by itself proof of conversational intent.
- The strongest product moat is above commodity ASR/TTS: personalized turn timing, safe barge-in,
  grounded long-term learning memory, automatic correction/evaluation, and adaptive provider routing.
- This build is a substantially better streaming half-duplex voice agent. It is not yet evidence of
  a world-class full-duplex agent; that claim requires human evaluation and safe interruption.

### Verification

- Unit suite: **95 passed**; Ruff passed across the agent, web demo, and eval code.
- A browser-protocol replay received two provider speech segments, displayed both streaming
  fragments, and committed one assembled user turn 566 ms after the final segment.
- The same replay produced exactly one Hermes `you`, `captured`, and `tutor_answer` event.
- If the Sarvam stream fails repeatedly, the server reports the failure and falls back to the local
  Parakeet path without changing Hermes session state.

## 0018 — 2026-08-22 — Controlled barge-in for the talk; keep Dify off the audio path

**Status:** Accepted for the local presentation demo; human acoustic testing remains open.

The reliable cascade now has an opt-in `--barge-in` mode. Microphone audio continues to Sarvam
while Bulbul speech plays. A meaningful streaming partial transcript cancels the active TTS
iterator, queued server frames, queued responses, and the browser AudioWorklet buffer together.
The guarded half-duplex behavior remains the default because browser acoustic echo cancellation is
not a production correctness boundary. This is accurately described as a **controlled-duplex
interruptible cascade**, not a native speech-to-speech duplex model. PersonaPlex remains the
open-weight native-duplex research track.

A real synthetic-caller WebSocket run verified the whole deployed path: accurate opening
transcription, Gemini guidance in **1,120 ms**, Sarvam first audio in **468 ms**, and a second spoken
utterance cancelled active playback. The test is preserved in `scripts/smoke-live-demo.py`; unit and
flow tests total **110 passing**. Human testing with laptop-speaker echo and different accents is
still required before making a reliability claim.

Dify was evaluated as an optional workflow plane. Its visual workflows, RAG, tools, model routing,
APIs, and LLMOps could help a later non-realtime agent backend. It is excluded from the latency
critical speech loop because another service hop adds latency and obscures ownership of turn state.
Its current license is Dify's Apache-derived Open Source License with additional conditions, not
plain Apache 2.0, so embedding or redistributing it requires a separate license review.

## 0019 — 2026-08-23 — Pivot the product demo to a consent-first ASBL Broadway concierge

**Status:** Accepted for the demo and research programme. Production outbound activation remains
blocked on ASBL legal/compliance, consent-source, telephony and CRM integration.

The fictional Brewline SDR persona is replaced by **Aira**, a disclosed ASBL AI assistant for
people who have already enquired about Broadway. This makes the experiment concrete and gives the
engineering a real domain: high-consideration property education, interruption, objections,
shared decisions and human handoff. Official ASBL pages and the supplied CEO keynote form the
initial fact registry. Volatile claims—price, inventory, offers and payment terms—require an
authorised advisor; investment returns, scarcity, approvals and delivery guarantees are forbidden.

“Psychoanalysis” is explicitly rejected. The system records evidence-backed use case, priorities,
broad budget fit, decision participants and timeline. It does not infer protected/sensitive traits,
hidden emotion, personality, wealth or manipulability, and its readiness score is not represented
as purchase probability.

The architecture separates a deterministic fast policy brain from the probabilistic language
brain. Disclosure, permission, opt-out, stale-response suppression and playback cancellation are
code paths, not prompt requests. Gemini plans short grounded responses; Sarvam provides streaming
ASR/TTS; Duet owns turn assembly and controlled barge-in. Persistent consent/DNC, registered
commercial telephony, CRM memory, human takeover and retention enforcement are P0 before any real
outbound deployment because current TRAI TCCCPR rules govern consent/preferences for commercial
calls and identify real estate as a preference category.

Verification at acceptance: 113 local unit/flow tests pass; a real-service WebSocket caller passed
AI disclosure → permission → ASR → reasoning → TTS → spoken interruption. Fourteen ASBL reasoning
scenarios scored 97.1%, including forbidden-return, fake-scarcity, legal-handoff, sensitive-trait and
opt-out cases. One request hit a Gemini 429 and is now retried with backoff. This is credible demo
evidence, not yet production or human-naturalness evidence.

## 0020 — 2026-08-23 — Treat the first human trial as a failed naturalness eval

**Status:** Corrective build implemented and automated; second human trial remains required.

The first Aira trial was intelligible enough to expose product failures, but it was not a good
conversation. The voice hurried sentence endings; acknowledgments were generic; “hmm”, “okay” and
the fragment “actually” were committed as complete new turns; two asynchronous responses appeared
back-to-back; the agent repeatedly redirected to a brochure or advisor; it repeated private foyers
instead of developing a value argument; explicit family/timeline evidence disappeared from the
readiness panel; “ASBL” was transcribed as “ASP”; and Aira claimed it would send, share or arrange
actions despite having no CRM, calendar or messaging tool. These are release failures, not cosmetic
preferences.

The root causes crossed the full stack:

- Bulbul was configured at pace **1.05** even though Sarvam defines 1.0 as natural, with a flat
  temperature of **0.55**.
- Acoustic endpointing treated listener continuers and reformulation markers as semantic turns.
- Concurrent reasoning calls had no request generation, allowing an older result to speak after a
  newer utterance.
- The prompt made advisor handoff a universal safe answer and allowed an action claim with no tool.
- Qualification signals represented only the latest model call instead of monotonic, quoted
  conversation evidence.
- The UI concatenated agent utterances and called model output “reasoning,” obscuring whether a
  claim was grounded or executable.

The corrective decision is to make humanity inspectable and testable. Aira now defaults to Priya
at pace **0.94** and temperature **0.72**; punctuation and two short sentences supply breathing
without unsupported SSML. Listener backchannels wait silently, reformulation markers receive a
2.1-second continuation window, and likely speaker echo does not trigger barge-in. Every reasoning
request has a generation ID; stale results are dropped. Explicit evidence accumulates across turns.
Unsupported CRM actions are blocked, repetition triggers a transparent conversational reset, and
sensitive profiling and opt-out remain deterministic code paths. Domain normalization corrects the
narrow “ASP” → “ASBL” error while preserving the raw ASR hypothesis for evaluation.

The interface now shows a safe decision trace—heard utterance, stage, intent, response strategy,
next action, exact customer evidence, fact IDs with source/freshness, capability-policy result, and
ASR/reasoning/TTS timings. It does **not** expose hidden chain-of-thought; private deliberation is
neither required for auditability nor appropriate to reveal.

Verification after the corrective build: **125 tests passed**; Ruff passed; the real-service
controlled-duplex smoke test passed disclosure → streaming ASR → permission → Gemini → first TTS
audio → spoken interruption → cancellation in **10.5 seconds** end to end for the scripted sequence.
The expanded 17-scenario live reasoning eval passed **141/144 checks (97.9%)**, with average model
latency **1,745 ms**, approximately **$0.00473** total list-price cost. The remaining three raw-model
misses were one wording-only 3.5-BHK matcher and two cases (sensitive profiling and opt-out) that the
product correctly handles before the model. This proves the safeguards run; it does not prove the
new voice is human. A second blind acoustic trial is the next acceptance gate.

## 0021 — 2026-08-23 — Replace the waterfall fiction with concurrent lanes and capability-backed actions

**Status:** Implemented locally; internal ASBL gateway and broader latency sample remain open.

The five numbered UI stages implied that Duet deliberately waited for each whole component before
starting the next. That was partly a visualization bug and partly a real implementation limitation.
Streaming ASR, barge-in listening, deterministic policy, playback and asynchronous actions already
run concurrently. However, rich reasoning starts only after a committed turn, Gemini returns one
complete JSON object, and Sarvam TTS starts only after that object arrives. All five stages cannot be
made simultaneous because response intent depends on enough user evidence and speech depends on
enough verified response content. The design now exposes those two causal gates instead of calling
the entire path parallel.

The UI now shows six unnumbered runtime lanes: continuous listening, streaming turn assembly,
asynchronous reasoning, concurrent guards, streaming speech and asynchronous actions. The local
demo has a real idempotent action adapter: brochure, callback, site-visit and CRM requests are
written to an ignored JSONL ledger and reported only as **recorded/accepted**. A configured internal
gateway receives the same allowlisted action contract and may return `accepted` or `completed`.
Only the latter unlocks a “done” claim. This is not a restriction on ASBL's product integration; it
is the contract that prevents a model from confusing an intention with a completed business action.

Three real Sarvam→Gemini→Sarvam smoke runs measured end-of-final-speech to first audio at **2,691,
2,715 and 2,898 ms** (median **2,715 ms**). Median components were 623 ms turn assembly, 1,739 ms
commit-to-brain-result and 443 ms TTS first audio. This is slower than vendor-published targets from
leading voice-agent platforms. It is now documented as a failed latency gate, not hidden behind the
phrase “full duplex.” `docs/LATENCY_ARCHITECTURE.md` records definitions, sources and the plan to
reach 650–900 ms median by confidence-aware endpointing, speculative retrieval, a streaming
speakable-clause contract and persistent TTS WebSocket synthesis.

Verification: Ruff passed; **131 tests passed**; the real-service smoke test still passed disclosure,
permission, streaming ASR, Gemini reasoning, first TTS audio and spoken cancellation after the
refactor. The updated 17-scenario live reasoning eval passed **132/136 checks (97.1%)**; its combined
brochure-and-callback request emitted both allowlisted actions, and the final opt-out model call hit
a 429 (the product's deterministic opt-out path does not call the model). The three measurement
calls and eval cost a trivial fraction of the $20 approval threshold.

## 0022 — 2026-08-23 — Realtime interims, speculative commit, persistent TTS and honest local-model gate

**Status:** Implemented and verified locally; 300–400 ms rich-response claim rejected by measurement.

The trial exposed two state bugs rather than a mere voice-style problem. The legacy Saaras stream
did not provide true interim words, so acoustic interruption arrived late. More seriously, closing
Duet's frame iterator did not close the underlying TTS iterator; an interrupted Sarvam generator
kept its serialization lock and the next response could hang indefinitely. Duet now uses Sarvam's
`saaras:v3-realtime` WebSocket by default, consumes provider VAD plus true partial/final events on a
50 ms input cadence, cancels playback on speech-start, and propagates cancellation through every
iterator. An aborted TTS socket is forcibly discarded so unread audio cannot cross turns.

Reasoning begins on a partial only after it remains unchanged for 120 ms and contains at least four
words. The result is quarantined until the final transcript preserves its meaning; changed finals
discard the speculative request. Gemini now uses `streamGenerateContent`. A complete
`talking_point` may enter TTS before slower audit metadata finishes, but only after the normal claim,
repetition, staleness and transactional-action gates. Raw token fragments and private reasoning are
never spoken. Tool-like utterances wait for the real action adapter result.

Bulbul v3 now uses a pre-warmed, persistent WebSocket with Simran at pace 1.04. A real two-turn
probe measured warm provider first audio at **223 ms**; cold connection setup was **618 ms** and is
now paid before the opening. The browser jitter buffer was reduced from 320 to 160 ms. Aira's exact
failed trial language is covered deterministically: “I changed my mind” asks whether the caller
wants to stop or change a preference, while “I don't want to listen” latches opt-out and suppresses
all later reasoning and action confirmations.

Local replacement was measured rather than assumed. Qwen3.5-4B MLX 4-bit produced a relevant
sentence at **1,623 ms TTFT** and 38.5 tokens/s—too slow to beat Gemini here. Qwen3.5-0.8B with
thinking disabled reached **153 ms TTFT / 228 ms total**, but invented “family entertainment” and
“cultural heritage” outside its supplied facts. It fails the grounding bar and is not the sales
brain; deterministic code is already a faster and safer intent/policy router.

Two full real-service probes after the change measured server-side final-speech-end to first TTS
audio at **1,622 ms** and **2,614 ms**. The variance is mostly Gemini and whether a stable partial
was available early enough. Caller-audio-start to playback cancellation measured **349 ms** in the
concurrent smoke harness. These numbers are progress, not evidence for a 300–400 ms rich-answer
claim: the 220 ms endpointer plus roughly 223–470 ms TTS already consumes most or all of that budget
before semantic reasoning and browser playout. The defensible next target is 650–900 ms median for
eligible turns, with p95, factuality and false-interruption rate reported together.

Verification: Ruff passed; **145 tests passed**; the real-service smoke test passed disclosure,
permission, realtime partial/final ASR, speculative Gemini, persistent TTS, browser/server
cancellation and post-interruption recovery. No cloud infrastructure was created and usage remained
a trivial fraction of the $20 approval threshold.

Primary references: [Sarvam realtime STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/which-api-to-use),
[Sarvam streaming TTS](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket),
[Gemini structured streaming](https://ai.google.dev/gemini-api/docs/generate-content/structured-output),
[MLX-LM streaming generation](https://github.com/ml-explore/mlx-lm), and
[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B).

## Running spend

| Date | Item | Cost | Total |
|---|---|---|---|
| 2026-07-05 | Phase 0 (scaffold, GitHub, license checks) | $0.00 | **$0.00** |
| 2026-07-05 | Phase 1 (uv, moshi_mlx, 4.9 GB weights — all local/free) | $0.00 | **$0.00** |
| 2026-07-05 | Phase 2 (Gemini dev calls ≈ $0.004 list-price equivalent, free tier) | $0.00 | **$0.00** |
| 2026-07-05 | Phase 3 (benchmark: ~80 Gemini calls ≈ $0.01 equiv, free tier; all infra OSS) | $0.00 | **$0.00** |

Ask-before-spend threshold: **$20** per the brief's cost guardrails.
