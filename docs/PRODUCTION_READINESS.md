# Production readiness: what still separates Duet from a dependable voice platform

Duet is now a measurable local product prototype. It is not yet a production voice platform. The
difference is not one better model: it is whether thousands of stateful, latency-sensitive calls remain
correct when providers slow down, users interrupt, tools retry, networks flap, deployments roll, and
operators need to explain exactly what happened.

This assessment uses public evidence from mature providers; it does not pretend to know ElevenLabs',
Bolna's or Giga's private implementation. ElevenLabs publicly describes simulated full/partial calls,
tool-call tests, probabilistic pass rates, CI integration, independent guardrails, real-time monitoring
and OpenTelemetry call traces. Those are useful external standards for Duet.

## Executive verdict

The strongest current parts are the interaction state machine, stable-partial speculation, generation-safe
cancellation, grounded sales policy, provider adapters, testable reasoning contract and now correlated
telemetry. The biggest blockers are:

1. **Isolation:** one process-global browser session, not one fault domain per call.
2. **Durability:** consent, do-not-contact, memory and action state are not yet transactional production data.
3. **Failure policy:** no measured multi-provider fallback, circuit breaker, admission control or regional plan.
4. **Transport:** no production WebRTC/PSTN adapter, transfer path or carrier compliance integration.
5. **Evidence:** no statistically credible human naturalness study, real phone-audio suite or sustained load test.
6. **Operations:** no deployment artifact, SLO/error budget, pager route, canary, rollback or incident runbook.
7. **Security:** no tenant/auth boundary, secrets manager, deletion workflow or completed threat model.

Do not rewrite the whole runtime at once. Graphify's local code graph found the live `Session` class to be
the largest coupling hub. A big-bang rewrite would risk the cancellation and barge-in invariants that took
real trials to discover. Extract one contract at a time and require behavior/latency parity after each move.

## Current maturity matrix

| Capability | Today | Production acceptance gate |
|---|---|---|
| Session lifecycle | One active browser session; server-side 240 s cap | Independent call actor/supervisor, deadline and cancellation scope; 100 concurrent soak without cross-talk |
| Audio ingress | Browser AudioWorklet, provider VAD, partial/final ASR | Jitter/loss/reconnect tests; codec/resample conformance; phone-band fixtures; overload backpressure |
| Turn taking | Stable-partial speculation, final semantic gate, interruption repair | False-barge, wrong-start, yield and repair metrics on consented real conversations |
| Reasoning | Gemini streaming with deterministic fast lane | Versioned prompts/models; timeout budget; replay; fallback; adversarial and tool tests on every release |
| Grounding | Static verified fact registry and claim guards | Signed/versioned product knowledge, freshness SLA, provenance on every dynamic claim, safe unknown path |
| Actions | Local idempotent ledger or allowlisted HTTPS gateway | Authenticated tool identity, idempotency keys, timeout/retry contract, confirmation state and reconciliation |
| Speech | Persistent Sarvam TTS, pacing and adaptive jitter | MOS/intelligibility suite; pronunciation lexicon; voice fallback; cancellation under packet loss |
| Telemetry | Langfuse + Prometheus + Loki/Alloy + Postgres, correlated and redacted | Retention/access policy, trace sampling, alerting, telemetry-loss alerts and cross-service propagation |
| Testing | 153 tests, live reasoning gate, synthetic service smoke, ASR/TTS/duplex harnesses | Release-blocking end-to-end simulations, repeated stochastic runs, phone fixtures, k6/chaos and rollback test |
| Privacy/safety | Consent-first persona, opt-out and content redaction | Durable consent/DNC before dialing, deletion SLA, PII inventory, threat model and legal review |
| Deployment | Local Mac/Docker observability | Immutable containers, TLS/WSS, auth, secrets manager, CI deploy, canary, rollback and runbooks |

## Target architecture

```text
                          control plane
  configuration ─ prompts ─ knowledge versions ─ eval registry ─ rollout policy
                                  │
                                  ▼
Browser / WebRTC / SIP / PSTN gateway
                 │ authenticated media + call events
                 ▼
Admission controller ─ rate limits ─ tenant quota ─ concurrency/load shedding
                 │
                 ▼
Per-call session supervisor (one isolated actor/task group)
  │ owns call_id, trace_id, consent, deadline, generation and cancellation
  ├── media ingress     jitter, codec, VAD, ASR and reconnect
  ├── turn manager      endpointing, stable partials and commit/reject
  ├── policy fast lane  consent, DNC, interruption, claims and action guards
  ├── conversation      bounded memory, retrieval, reasoning and tool planner
  ├── action executor   idempotency, auth, timeout, retry and confirmation
  └── media egress      TTS streaming, pacing, clear/mark and playout state
                 │
                 ├── Postgres: durable consent/call/action state
                 ├── object store: explicitly consented recordings only
                 └── telemetry port: OTel/Langfuse + Prometheus + Loki
```

The call supervisor—not the LLM—owns time. Every external operation gets a deadline shorter than the
remaining turn budget. Every result carries a generation ID. Late work is discarded. Barge-in cancels
the current generation across planning, TTS and transport. Tools are idempotent because timeout does not
tell us whether the remote side completed the operation.

## Reliability practices to adopt

### One call, one fault domain

- Replace `active["session"]` with a session registry backed by isolated task groups/actors.
- Bound every queue by time as well as count; emit pressure metrics and shed new calls before active calls degrade.
- Never share mutable conversation, provider sockets, generation counters or playback buffers across calls.
- Propagate one call ID and trace ID through transport, model, tool and persistence boundaries.
- Enforce absolute session deadline server-side and release every socket/task on disconnect.

### Explicit latency budgets

Use a budget, not a vague “low latency” goal. Proposed initial browser SLOs—not yet achieved standards:

| Segment | p50 target | p95 target |
|---|---:|---:|
| speech end → accepted turn | 150 ms | 300 ms |
| committed turn → first reasoning text | 250 ms | 600 ms |
| TTS request → first server audio | 250 ms | 500 ms |
| speech end → first audible response | 800 ms | 1,200 ms |
| verified barge-in → playback silence | 150 ms | 250 ms |

Report task success, wrong starts, false interruptions and factuality beside latency. A 400 ms answer that
misunderstands the caller is a regression. Use histograms and percentiles; averages hide tail pain.

### Provider resilience

- Define typed ASR, reasoner and TTS interfaces with capability metadata (streaming, language, sample rate).
- Add timeout, bounded retry with jitter, circuit breaker and health score per provider.
- Fallback by failure class: text clarification is safer than silently switching to a lower-quality ASR mid-turn.
- Pre-warm sockets, but expire and recreate unhealthy connections; never reuse a cancelled stream blindly.
- Measure fallback quality and latency in CI and staging. An untested fallback is wishful thinking.

### Tool correctness

- Validate tool input against a schema before execution and validate the result independently before speech.
- Generate an idempotency key from call, action type and normalized arguments.
- Separate `requested`, `accepted`, `completed`, `failed` and `unknown` states.
- Never say “scheduled” when only “requested” is known. Your internal adapter can permit candid claims only
  after it returns the corresponding durable status.
- Reconcile unknown outcomes asynchronously and expose them to the human operator.

### Guardrails without destroying latency

- Keep deterministic consent, opt-out, DNC, PII and claim rules in the fast lane.
- Run slower semantic safety checks concurrently where possible, but gate speech for high-risk claims/actions.
- Treat prompt instructions as one layer, not the security boundary. Validate user input and model output.
- Store the policy version with the call so behavior can be reproduced after policies change.
- Route uncertainty to a clarification or human; do not force the LLM to improvise.

### Evals are release specifications

Mature voice testing needs more than unit tests:

1. **Deterministic units:** endpointing, fragment merge, generation cancellation, idempotency and claims.
2. **Model behavior sets:** golden user turns, adversarial objections, multilingual/code-mix, repeated 5–20 times.
3. **Conversation simulations:** full and partial call trajectories, including tool failures and interruptions.
4. **Audio replay:** clean/noisy/reverberant/phone-band speech with exact expected events and WER/CER.
5. **Duplex tests:** overlap, backchannels, echo, false VAD, interrupt-and-repair and stale-audio leakage.
6. **Human blind study:** paired baseline/current clips; naturalness, intelligibility, trust and task success.
7. **Load/chaos:** k6/WebSocket concurrency, provider delay/error injection, reconnect and process termination.
8. **Production shadow:** score real consented calls without autonomous action before enabling traffic.

Every release should publish pass rate and failure buckets, not a single judge score. Stochastic tests require
multiple runs and confidence intervals. Keep a holdout set that prompt authors cannot tune against.

### Observability and operations

Duet now emits live traces, metrics, logs and summaries. Production still needs:

- RED metrics by tenant/provider/model/version: rate, errors and duration/latency;
- SLO dashboards and burn-rate alerts, including “telemetry disappeared” alerts;
- trace sampling that always retains errors, high latency, opt-outs and tool uncertainty;
- PII-safe structured fields and access-controlled raw audio/transcripts with deletion enforcement;
- deployment annotations, prompt/model/config version tags and release comparison dashboards;
- runbooks for provider outage, runaway spend, DNC failure, audio corruption and tool inconsistency;
- a named on-call owner and kill switch that stops dialing without taking down audit access.

## Migration plan

### P0 — credible in-house pilot

- Extract a transport-neutral `SessionSupervisor`; support 10 concurrent isolated browser sessions.
- Persist lead, consent, DNC, call and action records transactionally before external actions.
- Connect the authenticated ASBL action gateway and human handoff.
- Containerize the app; Caddy TLS/WSS; signed session tokens and origin checks.
- Add provider deadlines/circuit breakers and explicit clarification fallback.
- Build 50–100 ASBL scenarios plus 20 consented phone/audio fixtures.
- Run k6 load and fault injection; define dashboards, alerts and runbooks.
- Use only allowlisted employees/consenting leads in shadow or assisted mode.

### P1 — controlled production

- Telephony adapter and compliant outbound workflow; transfer/recording controls.
- Canary by staff/test cohort, then 1%, 5%, 20%; automatic rollback on SLO or safety regression.
- Daily eval replay against the deployed model/prompt/knowledge versions.
- Multilingual English–Telugu–Hindi/code-mix evaluation before enabling those languages.
- Provider failover and capacity planning based on measured concurrent calls.

### P2 — platform/open source

- Stable provider/transport/tool SDK contracts and reference adapters.
- Multi-tenant quotas, authorization, config control plane and versioned knowledge ingestion.
- Public benchmark artifacts stripped of customer data.
- Open-source the orchestration/eval/control plane; sell managed telecom, compliance, reliability and integrations
  only after the in-house system demonstrates measurable conversion or productivity value.

## What “production-grade” should mean here

It does not mean “sounds impressive in one demo.” It means Duet can prove:

- no call starts without valid consent and no opted-out lead is called again;
- no fabricated RERA/project/tool claim reaches speech;
- active calls remain isolated under concurrency and failure;
- barge-in, latency, task success and human trust meet published SLOs;
- every external action is auditable and reconcilable;
- a release can be canaried, observed, stopped and rolled back safely;
- cost per successful qualified lead/site visit is better than the human-assisted baseline.

Useful public references: [ElevenLabs testing methodology](https://elevenlabs.io/blog/testing-conversational-ai-agents),
[agent testing](https://elevenlabs.io/docs/eleven-agents/customization/agent-testing),
[guardrails](https://elevenlabs.io/docs/eleven-agents/best-practices/guardrails),
[real-time monitoring](https://elevenlabs.io/docs/eleven-agents/guides/realtime-monitoring),
[OpenTelemetry traces](https://elevenlabs.io/docs/eleven-agents/customization/opentelemetry-traces), and
[conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow).
