# Duet: Voice AI Engineer + Technical Talk Plan

**Outcome:** ship a defensible, live voice-agent experiment and give a talk whose claims are backed by code, audio, traces, and reproducible evaluation.

The talk and the learning program are the same project. Every section of the talk must correspond to an artifact we built and a result we measured. No slide may claim more than the demo proves.

## The thesis

The frontier opportunity is not to pretrain a speech foundation model. It is to build the interaction, evaluation, data, and production system around open-weight speech models—and to post-train conversational dynamics with a much smaller budget than frontier pretraining.

Duet's near-term research question:

> Can an open-weight, role-conditioned duplex model deliver a substantially more natural English conversation than a tuned cascade on one Mac, and what fails before it approaches commercial realtime systems?

The India follow-on question:

> Can consent-cleared, dual-speaker or accurately diarized Indian sales conversations improve multilingual turn-taking and code-switching without degrading semantic quality or privacy?

English-to-English is the first proof. Multilingual training starts only after the English benchmark and data-governance pipeline pass.

## The abstraction ladder

You should be able to explain and debug each level. Stop descending when the lower level no longer changes the design decision.

### Level 1 — Human interaction

- Turns are not alternating boxes; people pause, overlap, backchannel, interrupt, repair, and abandon utterances.
- Know the measurable behaviors: pause handling, smooth handoff, backchannel precision/timing, user interruption recovery, semantic repair.
- Graduation evidence: label five real calls by hand and explain every overlap event.

### Level 2 — Audio and transport

- PCM, sample rate, frame duration, codecs, jitter, echo, acoustic echo cancellation, packet loss, resampling, clock drift.
- The 80 ms Mimi frame is a hard scheduling budget, not a marketing latency number.
- Distinguish model-generation time from time-to-audible-playback.
- Graduation evidence: draw one timestamped trace from microphone capture to audible speaker output and account for every millisecond.

### Level 3 — Speech models

- Cascade: VAD/endpointing → ASR → text reasoning → TTS.
- Speech-native cascade: audio encoder → LLM → streaming speech decoder.
- End-to-end duplex: parallel user/agent audio streams with learned interaction policy.
- Understand neural audio codecs, semantic versus acoustic tokens, delayed streams, streaming KV caches, quantization, and sampling.
- Graduation evidence: run the same scenario through local cascade, Moshi, and PersonaPlex; explain the quality/latency differences from architecture rather than brand names.

### Level 4 — Interaction policy

- Acoustic speech-end is evidence, not proof that the user yielded the floor.
- Separate content intelligence from conversational dynamics.
- Understand pause policy, takeover policy, barge-in, backchannel gating, stale-response cancellation, and playback ownership.
- Graduation evidence: reduce an interaction failure with an eval-driven change without worsening another axis.

### Level 5 — Agent semantics

- Grounding, tools, memory, role adherence, correction, action confirmation, and privacy boundaries.
- Tool success and conversational timing must be evaluated together.
- Graduation evidence: the agent completes one grounded tool action, survives interruption, and never records an unconfirmed action.

### Level 6 — Production system

- WebRTC, AEC, admission control, concurrency, warm pools, cold starts, observability, consent, retention, deletion, rate limits, failure fallbacks, and cost per successful task.
- Server state must reflect what the user has actually heard, not merely what the server generated.
- Graduation evidence: a public or private remote deployment survives ten scripted calls, one backend outage, and one forced restart with trace continuity.

### Level 7 — Training and research

- Dataset rights, two-channel conversation extraction, diarization error, segment mining, supervised fine-tuning, LoRA, preference optimization, GRPO, reward hacking, semantic-preservation rewards, and human evaluation.
- Graduation evidence: reproduce one interaction-axis post-training experiment on a small, consent-cleared dataset and publish the ablation.

## What we build next

### Gate 0 — Freeze the truth (one day)

- Commit or separately preserve the current dirty worktree; do not mix unrelated changes.
- Update README status: current reliable path is half-duplex; interruption remains disabled there; PersonaPlex is experimental.
- Add a machine-load preflight that refuses realtime inference when the 80 ms budget cannot be met.
- Produce a clean-clone verification script.

**Exit:** repository state, demo claims, and actual behavior agree.

### Gate 1 — A demo that cannot embarrass us (two to three days)

- Add PersonaPlex as a separate backend, not a fork of the Moshi code path.
- Measure q4 step p50/p95, memory, startup time, and sustained missed-frame rate.
- Browser demo must show: user waveform, partial/final transcript, agent text, agent waveform, current speaker state, dropped frames, and end-to-end latency.
- Add a deterministic fallback: if PersonaPlex misses its realtime budget or fails to load, switch to the local guarded cascade and state this visibly.
- Prepare a recorded demo clip as backup. Never rely only on a live model during the talk.

**Exit:** three consecutive five-minute sessions without hallucinated user speech, self-echo, process crash, or unrecoverable stall.

### Gate 2 — Comparative evidence (two days)

Run identical English scenarios through:

1. local guarded cascade (Silero + Parakeet + reasoning + Piper),
2. Sarvam speech plane + Duet interaction plane,
3. Moshi q4,
4. PersonaPlex q4,
5. one commercial reference when an API key and budget are approved.

Report:

- takeover rate by interaction axis,
- pause false-positive rate,
- handoff p50/p95,
- interruption stop latency and repair quality,
- backchannel precision/recall/timing,
- WER on real microphone and telephony audio,
- TTS naturalness MOS and intelligibility,
- task success / grounding score,
- missed-frame rate and playback divergence,
- cost per minute and cost per successful task.

Use repeated trials and fixed audio inputs where possible. Preserve every failed trajectory.

**Exit:** a result table whose methodology a stranger can reproduce.

### Gate 3 — Human evidence (one week, mostly coordination)

- Minimum 10 blinded raters; randomize system labels and order.
- Rate naturalness, intelligibility, responsiveness, politeness, trust, and task success separately.
- Include accented English and noisy-room scenarios.
- Publish confidence intervals and raw anonymized ratings.

**Exit:** no claim of "humanlike" or "on par" without human evidence.

### Gate 4 — Indian multilingual dataset pilot (after legal clearance)

- Start with 20–50 consent-cleared calls, not the whole archive.
- Redact PII before humans or models access training artifacts.
- Preserve stereo/dual-channel audio when available. If mono, quantify diarization error before using turn labels.
- Build a language/code-switch inventory and a telephony-channel test set.
- First use the data for evaluation and error analysis. Train only after the eval reveals a specific, recurring failure.
- For post-training, mine short segments for four axes: pause handling, smooth turn-taking, backchanneling, and interruption/repair.
- Optimize interaction rewards while retaining a semantic-quality reward; run English-retention and multilingual-transfer ablations.

**Exit:** one narrow post-training result with consent provenance, held-out callers, and no regression on English.

### Gate 5 — Private deployment (one week)

- Browser/WebRTC client with AEC and jitter buffering.
- GPU backend separate from observability and batch workloads.
- Session admission control, warm-up, health checks, fallback, and hard cost cap.
- Append-only consent and retention records; one-click deletion.
- Playback-aligned dialogue state: tool actions and memory updates occur only after the relevant response was actually heard or explicitly confirmed.

**Exit:** ten remote sessions and an operational runbook.

## The technical talk

### Title

**Full Duplex Was the Easy Part: Building and Measuring an Open Voice Agent**

Subtitle: *From an 80 ms audio loop to real turn-taking, hallucinated speech, and PersonaPlex.*

### Audience promise

In 30 minutes, the audience will understand why a voice agent is not ASR + LLM + TTS, see a working open-weight system, and leave with a reproducible eval framework for deciding whether a voice stack is actually natural.

### 30-minute narrative

1. **Cold open — 90 seconds:** play two anonymized clips: cascade dead air and duplex overlap. Ask the audience which failure is worse.
2. **The mental model — 4 minutes:** human conversation as two continuous streams; explain the 80 ms frame and why "turn" is an application concept, not a physical one.
3. **Three architectures — 4 minutes:** cascade, speech-native pipeline, end-to-end duplex. State where information and latency are lost.
4. **What we built — 4 minutes:** Duet's browser, PersonaPlex/Moshi experiments, interaction metrics, ASBL grounding, and fallback speech plane.
5. **Live demo — 4 minutes:** normal question, thoughtful pause, interruption, correction, tool/memory action. Show the timeline, not only the audio.
6. **The failures — 5 minutes:** hallucinated transcript from silence, self-echo, contention, wrong ASR default chosen from a nondiscriminating eval, and hybrid p95 tail. Each failure becomes an eval.
7. **The result table — 3 minutes:** compare systems on takeover, handoff, WER, MOS, task success, and cost. If PersonaPlex loses, show it.
8. **Why a small team can matter — 2 minutes:** PersonaPlex fine-tuned Moshi in six hours on eight A100s rather than pretraining a frontier model; the leverage is data, post-training, interaction policy, and evaluation.
9. **Close — 2 minutes:** India-specific research program: consent-cleared multilingual sales conversations, English-first proof, interaction-axis RL, and a public benchmark cadence.

### Demo contract

The live demo is not ready until it can show all four behaviors:

1. remain silent through a mid-sentence thinking pause,
2. respond within 300 ms after a genuine handoff,
3. stop within 300 ms when interrupted and repair coherently,
4. complete one grounded ASBL tool action with explicit confirmation.

Have a 90-second recorded backup using the exact same build and scenario.

### Slides that must contain evidence

- An 80 ms frame-budget timeline with measured stage durations.
- Waveform + transcript + speaker-state trace from one successful and one failed call.
- The four interaction axes and their definitions.
- One honest comparison table with confidence intervals.
- One architecture diagram showing playback-aligned state.
- A cost ladder: frontier pretraining, foundation-model fine-tuning, our POC, inference per minute.
- The data-governance boundary for Indian call recordings.
- A final "what we know / what remains unproven" slide.

## Research curriculum

Read papers to answer build questions, not to accumulate summaries.

### Foundation

1. **Moshi** — delayed streams, Mimi codec, parallel user/agent audio.
2. **Full-Duplex-Bench v1.5** — pause, turn, backchannel, and interruption metrics.
3. **PersonaPlex** — hybrid text/audio role and voice conditioning; synthetic service data; open-weight duplex fine-tuning.

### Current frontier

4. **Multi-Faceted Interactivity Alignment** — GRPO over four interaction axes plus semantic-quality reward.
5. **PACE** — playback-aligned context and the divergence between generated and actually heard dialogue state.
6. **M3-DuplexBench** — multilingual, multi-turn, multidomain evaluation.
7. **DuplexSLA / Full-Duplex-Bench v3** — speech, language, action, and tool-use evaluation.
8. **HumDial-FDBench** — real human dual-channel interaction data and challenge methodology.

For every paper, produce four outputs: a one-page architecture note, one reproduced figure/table, one code experiment, and one criticism relevant to Duet.

## When you may call yourself a voice AI engineer

Not after reading the list. Call yourself one when you can demonstrate all of these:

- trace and debug audio from microphone to playback,
- explain and benchmark cascade and duplex architectures,
- measure WER, MOS, RTF, TTFB, handoff, takeover, backchannel, and interruption repair,
- make one interaction metric better without silently breaking another,
- deploy WebRTC/AEC with observability and graceful fallback,
- implement consent, retention, deletion, and privacy boundaries,
- prepare a legally usable speech dataset and quantify annotation/diarization error,
- adapt or post-train an open speech model and run honest ablations,
- publish reproducible results and preserve failures.

The shortest credible path is not a certificate. It is the Duet repository, one reliable demo, one public benchmark, one small post-training result, and one production deployment.

## Immediate next actions

1. Stabilize and instrument PersonaPlex realtime inference.
2. Tune the reliable cascade against the same interaction scenarios.
3. Capture 20 real English microphone sessions and correct transcripts.
4. Run the five-system comparison and blinded evaluation.
5. Build the final slide deck only after the comparison table exists.
6. Use the talk date as a forcing function, but never let it authorize an unmeasured claim.
