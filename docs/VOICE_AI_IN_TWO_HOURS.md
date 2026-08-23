# Two-hour Duet immersion: from novice to an articulate voice-AI builder

Two hours cannot make anyone an expert. It can make you operationally fluent enough to trace this system,
change it safely, identify dishonest claims and answer architectural questions without bluffing. Expertise
comes from debugging real calls and repeatedly measuring failures.

Use a timer. For every block: read, inspect the exact file, do the exercise, answer the checkpoint aloud.

## 00:00–00:10 — Build the one-page mental model

Write this from memory:

```text
audio frames → speech detection → partial transcript → turn commit
             → deterministic policy → LLM plan/tools → speakable text
             → streaming synthesis → jitter-managed playback
```

Across the whole line run cancellation, consent, deadlines, state ownership, observability and cost controls.

Read: `README.md` through “Running architecture” and `docs/ARCHITECTURE.md` sections 1–3.

Checkpoint: explain why voice AI is a continuous-time distributed control system, not “an LLM with a mic.”

## 00:10–00:25 — Audio, streaming and transport

Learn sample rate, PCM, frame duration, buffering, jitter, echo cancellation and resampling. Inspect the
AudioWorklet and WebSocket binary handling. Calculate one Duet frame: 1,920 float32 samples, 80 ms, 7,680 bytes.

Trade-off: smaller chunks reduce responsiveness delay but increase scheduling/network overhead and underrun
risk. WebSockets preserve application simplicity; WebRTC is the production media choice for jitter, packet
loss, NAT traversal and adaptive playout.

Checkpoint: why can reducing every buffer make speech *less* intelligible?

## 00:25–00:42 — VAD, ASR, endpointing and stable partials

Read `agent/duet_agent/asr.py`, `turns.py` and the Sarvam receiver/finalizer in `web-demo/server.py`.

Know the separation:

- VAD: is there speech?
- ASR: what words are hypothesized?
- endpointing: has the caller completed the thought?
- turn policy: what should the agent do with this event?

WER measures substitutions + deletions + insertions over reference words. It does not measure endpoint delay,
speaker attribution or whether an interruption was handled appropriately.

Exercise: say “I’m looking for a three bedroom… actually, for my parents” with a deliberate pause. Watch how
partials change and identify the final commit event.

Checkpoint: why can the lowest-WER offline model be the worse live agent recognizer?

## 00:42–01:00 — Duplex, floor control and cancellation

Read the normal-turn, barge-in and state-machine diagrams in `docs/ARCHITECTURE.md`; inspect
`handle_speech_start`, `interrupt_playback`, `_accept_transcript` and request-ID checks.

Differentiate:

- half duplex: listening stops while the agent speaks;
- controlled duplex: listening remains live and policy cancels/repairs;
- native full duplex: a model continuously consumes and emits synchronized audio streams.

An interruption is not merely “stop audio.” It can mean backchannel, pause, correction, new topic, opt-out or
background noise. Acoustic floor transfer should be fast; semantic interpretation can follow.

Exercise: draw transitions for “mm-hmm,” “wait,” “stop calling,” “actually I need a 3.5 BHK,” and a cough.

Checkpoint: why is cancelling on any detected sound both fast and wrong?

## 01:00–01:18 — Reasoning, grounding, tools and quotas

Read `reasoning.py`, `persona.py`, `actions.py` and `rate_limits.py`.

The LLM proposes bounded structured guidance. It does not own consent, opt-out, audio, durable tool success or
truth. Static claims require registered fact IDs. Volatile data requires a current authenticated tool. Actions
have requested/accepted/completed/failed states and idempotency keys.

Gemini quota is per project. Duet's process-local limiter controls RPM, rolling-24-hour requests and in-flight
calls. Quota pressure becomes immediate graceful degradation—not delayed speech.

Exercise: add a fake “guaranteed appreciation” fact mentally and explain every layer that should reject it.

Checkpoint: why can a larger local LLM increase model intelligence while reducing product reliability?

## 01:18–01:32 — TTS, naturalness and latency budgets

Read `tts.py` and `docs/LATENCY_ARCHITECTURE.md`.

Know four independent qualities:

1. wording and conversational strategy;
2. voice timbre/prosody/pronunciation;
3. timing and turn-taking;
4. transport smoothness and underruns.

Measure endpoint→brain, Gemini TTFT, TTS TTFB, endpoint→first audible audio, cancellation delay, p50/p95/p99,
and task success. A fast wrong start is not a latency win.

Exercise: diagnose “robotic and hurried” without saying “change the model” until you separate these four axes.

Checkpoint: why does total synthesis RTF matter less to a listener than first-byte time and chunk continuity?

## 01:32–01:47 — Reliability and observability

Read `live_telemetry.py`, `telemetry.py`, `docs/VPS_DEPLOYMENT.md` and open all three UIs.

Trace one call by `session_id`:

- Langfuse: the LLM generation and pipeline spans;
- Prometheus/Grafana: rates, active sessions and latency distributions;
- Loki: chronological structured events;
- Postgres: one durable call summary and cross-reference trace ID.

Understand bounded queues, backpressure, fail-silent telemetry, health versus readiness, rate limiting, circuit
breakers, fallbacks, canaries, rollback and error budgets.

Checkpoint: if Langfuse is down, what degrades? If Sarvam is down, what degrades? Why are those answers different?

## 01:47–02:00 — Evals, honest conclusions and presentation rehearsal

Read `eval/README.md`, `docs/RESEARCH_DIRECTION.md` and `$\tau$-Voice` from the reading list.

Unit tests cover deterministic code. Model golden sets cover structured behavior. Audio evals need WER, TTFB,
turn timing, wrong starts, task completion and blind human ratings. Realistic accents/noise/interruptions are a
separate distribution, not “extra polish.”

Give this five-minute narrative aloud:

1. Voice agents fail in the spaces between models: endpointing, overlap, state and tools.
2. We built a measured ASBL concierge to expose those failures.
3. The architecture overlaps safe work but preserves causal commit gates.
4. It cancels quickly, grounds claims and makes every turn inspectable.
5. The current result is real but imperfect: 2.169 s rich response, 198 ms cancellation, single-session.
6. The opportunity is the evaluation-and-control layer, not pretending we trained a frontier speech model.

Final checkpoint: answer “what evidence would falsify your thesis?” A correct answer includes no naturalness
improvement in blind tests, higher wrong-start/task-failure rates, unacceptable provider economics, or loss of
reliability under realistic Indian phone audio.

## Continue in Hermes Brain

The private, validated learning run is intentionally outside Duet at:

```text
/Users/sharat/Downloads/CURIOUS/hermes-brain/learning/duet-production-voice-ai/
```

Use its recall questions and applied exercise after this sprint. Record your score with:

```bash
cd /Users/sharat/Downloads/CURIOUS/hermes-brain
python3 scripts/brain.py review duet-production-voice-ai --correct N --total TOTAL \
  --notes "What I could not explain without looking"
```

The article is a private draft until you review it; no agent may approve or publish it for you.
