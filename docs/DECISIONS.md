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

## Running spend

| Date | Item | Cost | Total |
|---|---|---|---|
| 2026-07-05 | Phase 0 (scaffold, GitHub, license checks) | $0.00 | **$0.00** |
| 2026-07-05 | Phase 1 (uv, moshi_mlx, 4.9 GB weights — all local/free) | $0.00 | **$0.00** |
| 2026-07-05 | Phase 2 (Gemini dev calls ≈ $0.004 list-price equivalent, free tier) | $0.00 | **$0.00** |
| 2026-07-05 | Phase 3 (benchmark: ~80 Gemini calls ≈ $0.01 equiv, free tier; all infra OSS) | $0.00 | **$0.00** |

Ask-before-spend threshold: **$20** per the brief's cost guardrails.
