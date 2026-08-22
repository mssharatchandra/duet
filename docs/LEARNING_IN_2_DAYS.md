# Become operationally fluent in applied voice AI in two days

Two days will not make anyone a voice-AI expert. It can make you capable of explaining, running, measuring
and debugging this system without bluffing. Expertise comes after repeated real-call failures. The goal here
is a strong first 80%: understand the abstractions, trace one call end to end, change behavior safely, read
the metrics, and defend the engineering decisions in front of experienced engineers.

Use the repo as the textbook. For every module: learn the idea, inspect the named code, run the exercise,
then answer the checkpoint aloud without notes.

## Mental model first

A production cascade is not “speech in, speech out.” It is a distributed real-time control system:

```text
sound → frames → speech detection → partial words → committed turn
      → policy/reasoning/tools → speakable text → synthesized frames → playout
```

Meanwhile, cancellation, consent, deadlines, provider failures, traces and actions flow across those stages.
“Duplex” means listening can remain active while speaking; it does not mean causality disappears. You can
speculate early, but you still need a commit rule before speaking uncertain content.

## Day 1 — understand the machine

### 09:00–10:00 — Audio as data

Learn:

- sample rate (24 kHz means 24,000 samples/second), bit depth and channels;
- PCM frames, frame duration, buffering and why latency accumulates;
- resampling and why phone audio (often narrowband) differs from a laptop microphone;
- echo, noise, jitter, packet loss and underrun.

Read:

- `web-demo/audio-processor.js` for browser capture/playout;
- the frame constants and WebSocket binary handling in `web-demo/server.py`;
- `agent/duet_agent/asr_util.py`.

Exercise: calculate the bytes and duration of one browser frame. Find every buffer that can delay it.

Checkpoint: explain why making one buffer smaller may improve latency but create robotic glitches.

### 10:00–11:15 — VAD, ASR and endpointing

Learn:

- VAD asks “is someone speaking?”; ASR asks “what words?”; endpointing asks “is the turn complete?”;
- partial hypotheses can change; final transcripts still can be wrong;
- WER = substitutions + deletions + insertions divided by reference words;
- endpoint latency and WER are separate axes.

Read:

- `agent/duet_agent/turns.py`;
- Sarvam realtime handling in `web-demo/server.py`;
- `eval/asr/run_asr_eval.py` and `eval/asr/README.md`.

Exercise: run the ASR eval on two models/conditions. Inspect one substitution, deletion and insertion.

Checkpoint: explain why the most accurate offline ASR may be a worse live-agent ASR.

### 11:30–13:00 — Turns, duplex and interruption

Learn:

- half-duplex, controlled duplex and native full duplex;
- acoustic floor ownership versus semantic interruption meaning;
- backchannel, barge-in, pause request, opt-out and new-question transitions;
- generation IDs, cancellation propagation and stale audio.

Read:

- `docs/LATENCY_ARCHITECTURE.md`;
- `docs/RESEARCH_DIRECTION.md`;
- `interrupt_playback`, `_accept_transcript` and speculation methods in `web-demo/server.py`;
- related tests in `agent/tests/`.

Exercise: draw the state transitions for “wait,” “stop calling,” “actually…,” and a complete new question.

Checkpoint: explain why immediately muting on any noise is not robust barge-in.

### 14:00–15:15 — The conversation brain

Learn:

- the LLM is a probabilistic semantic planner, not the session controller;
- prompts, bounded history, structured outputs and streamed output;
- deterministic fast paths for consent, opt-out and common repair;
- grounding, retrieval, source freshness and “unknown” behavior.

Read:

- `agent/duet_agent/reasoning.py`;
- `agent/duet_agent/persona.py`;
- `eval/reasoning/`;
- `docs/ASBL_VOICE_AGENT.md`.

Exercise: add one allowed fact and one forbidden volatile claim; add a golden eval before changing the prompt.

Checkpoint: explain why a local 20B model may improve knowledge/reasoning but worsen latency, operations and
grounding—and why model size is not an automatic product-quality win.

### 15:15–16:15 — Actions and honest speech

Learn:

- tool schema, authentication, authorization, timeout, retry and idempotency;
- requested versus accepted versus completed versus unknown;
- action result grounding: speech must reflect durable state, not intention.

Read:

- `agent/duet_agent/actions.py` and its tests.

Exercise: simulate a timeout after the remote tool accepted a site visit. Explain how the idempotency key and
reconciliation prevent duplication or a false spoken confirmation.

Checkpoint: answer “why can’t the model simply call the CRM and say it worked?”

### 16:30–17:30 — TTS and perceived humanity

Learn:

- TTFB, real-time factor, chunk boundaries, prosody, pronunciation and pacing;
- why low TTFB plus poor chunking can sound worse than a slightly slower coherent phrase;
- jitter buffers, absolute-clock pacing and cancellation.

Read:

- `agent/duet_agent/tts.py`;
- TTS loops in `web-demo/server.py`;
- `eval/tts/`.

Exercise: compare one sentence at two pace/buffer settings and record TTFB, underruns and a human preference.

Checkpoint: separate voice quality, wording quality, turn timing and transport smoothness in your diagnosis.

### 17:30–18:30 — Trace a real call

Start the demo and observability stack. Make one consented test call. Find the same `session_id` in:

- browser decision trace;
- Langfuse generation;
- Prometheus metrics;
- Loki structured event;
- Postgres/Grafana call summary.

Checkpoint: tell the story of the slowest turn using evidence rather than intuition.

## Day 2 — learn to productionize and present

### 09:00–10:15 — Latency engineering

Learn:

- critical path, concurrency versus causality and Little's Law;
- cold start, TTFT, TTFB, endpoint-to-audio and tail latency;
- speculative execution, commit/rollback and pre-warming;
- why p50/p95/p99 matter more than one demo.

Read `docs/LATENCY_ARCHITECTURE.md` and Decision 0022.

Exercise: create a latency budget for a 1.2 s p95 turn. Mark what can overlap and what cannot.

Checkpoint: defend why Duet is not currently a 300–400 ms rich-response system.

### 10:15–11:30 — Evals as the specification

Learn:

- deterministic unit tests versus stochastic model evals;
- golden sets, adversarial sets, holdouts, repeated trials and confidence intervals;
- WER/CER, TTFB/RTF, Takeover Rate, wrong starts, task success, MOS and trust;
- regression gates and why an LLM judge alone is insufficient.

Read `eval/README.md`, `docs/BLIND_EVAL.md` and the test workflow.

Exercise: write one failed-trial transcript as an eval with explicit pass/fail criteria. Run it repeatedly.

Checkpoint: explain “evals are the new PRDs” using this project, not a slogan.

### 11:45–13:00 — Reliability architecture

Learn:

- per-call isolation, bounded queues, backpressure and admission control;
- deadlines, cancellation scopes, circuit breakers, fallback and load shedding;
- stateless workers versus durable call state;
- canary, rollback, kill switch, SLO and error budget.

Read `docs/PRODUCTION_READINESS.md` and `docs/ARCHITECTURE.md`.

Exercise: explain what happens when Gemini is slow, Sarvam disconnects, Postgres is down and Loki is full.

Checkpoint: identify which failures should degrade the conversation and which must never touch audio.

### 14:00–15:00 — Privacy, safety and outbound compliance

Learn:

- consent purpose, recording notice, DNC, retention/deletion and least privilege;
- PII inventory and why transcripts/recordings are more sensitive than aggregate metrics;
- RERA grounding and misleading-claim risk;
- human transfer and the difference between policy and prompt.

Read the trust sections of `docs/ASBL_VOICE_AGENT.md`, `docs/MARKET_ANALYSIS_INDIA.md`, `.env.example` and
the redaction code in `agent/duet_agent/live_telemetry.py`.

Exercise: verify a default trace contains a hash/length, not the transcript. Describe the approval needed to
use old sales calls for evaluation or training.

Checkpoint: explain why legal/compliance is a product control-plane requirement, not a launch checkbox.

### 15:00–16:00 — Economics and build/buy decisions

Learn:

- cost per minute is less important than cost per successful outcome;
- hosted API price versus GPU utilization, operations and fallback cost;
- what to open-source and what can become managed differentiation;
- why India's BPM number is market context, not Duet's TAM.

Read `docs/MARKET_ANALYSIS_INDIA.md`.

Exercise: build a spreadsheet with leads, contact rate, minutes, cost/minute, qualification and site-visit
conversion. Compare human, hosted platform and Duet assumptions; sensitivity-test the uncertain inputs.

Checkpoint: state the business hypothesis in falsifiable terms.

### 16:00–17:00 — Research literacy

Read the abstract/system/evaluation/limitations—not every equation—of Moshi, PersonaPlex, Full-Duplex-Bench
and tau-Voice. For each, write:

1. problem and claimed contribution;
2. system boundary;
3. datasets/evals;
4. strongest result;
5. limitation;
6. what experiment Duet can reproduce.

Checkpoint: explain why guarded speculative duplex is a research question, not yet a novel paradigm claim.

### 17:00–18:30 — Rehearse the technical talk

Use `docs/talk/Duet-Voice-AI-Engineering-Talk.pptx` and the speaker notes. Give the talk twice:

- pass one: record without stopping;
- pass two: cut jargon, add measured caveats, and keep the live demo under three minutes.

Be ready for these questions:

1. Why not ElevenLabs/Bolna/Giga?
2. Why not one end-to-end duplex model?
3. What exactly runs in parallel?
4. What are measured p50/p95 numbers?
5. How do you prevent false claims and duplicate actions?
6. What happens on provider failure?
7. Why is old sales-call data legally/technically risky?
8. What would falsify the business and research theses?

## Your final practical exam

Without reading, whiteboard:

- the audio and control flow from microphone to speaker;
- the four interruption outcomes;
- the latency budget and two unavoidable causal gates;
- the trace/metric/log/database correlation path;
- the P0 production migration;
- the ASBL-first market wedge and falsifiable KPI.

Then make a small code change by first adding an eval, run the complete local gate, inspect one trace, and
explain the result. If you can do that, you can honestly say: **“I have built and debugged an applied
streaming voice-agent system and understand its production boundaries.”** Keep earning “voice-AI engineer”
through real calls, incident reviews and repeated measurements.
