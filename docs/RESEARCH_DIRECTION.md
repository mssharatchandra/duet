# Guarded Speculative Duplex: research direction

**Working paper title:** *Guarded Speculative Duplex: Auditable Low-Latency Voice Agents over Modular Speech and Language Models*

**Status:** research proposal, not a novelty or performance claim.

## One-sentence hypothesis

Starting semantic work from stable partial ASR while quarantining it behind final-transcript, grounding, capability and interruption gates can reduce perceived response latency without increasing wrong starts, stale speech, unsafe actions or task failure.

## Novelty boundary

The following ideas are established prior art and must not be claimed as Duet inventions:

- low-latency streaming ASR → LLM → TTS cascades;
- native full-duplex speech-to-speech models;
- simultaneous listening and speaking;
- asynchronous retrieval or LLM augmentation;
- voice activity detection and barge-in cancellation;
- LLM guardrails or tool confirmation in isolation.

Representative prior work includes [Moshi](https://arxiv.org/abs/2410.00037), [PersonaPlex](https://arxiv.org/abs/2602.06053), [Kyutai Unmute](https://github.com/kyutai-labs/unmute) and [MoshiRAG](https://kyutai.org/blog/2026-04-30-moshi-rag/).

Duet's candidate contribution is their **composition and evaluation as a typed, auditable concurrency protocol**:

1. stable-partial reasoning starts before endpoint commit;
2. a final transcript semantically validates or cancels the speculative generation;
3. deterministic policy can pre-empt the semantic lane at any time;
4. generation IDs prevent stale reasoning or audio from crossing turns;
5. interruption repair distinguishes pause, vague correction, complete question and opt-out;
6. action speech is gated on an idempotent capability acknowledgment;
7. the trace records evidence, sources, decisions, cancellations and timings without exposing private chain-of-thought.

This may be a useful systems contribution even if no individual mechanism is new. Whether it is publishably novel must be decided by a systematic literature review and reviewer feedback, not by the project itself.

## System model

Duet is not a monolithic mixture-of-experts model. It is an event-driven distributed state machine.

```text
audio frames ──► streaming ASR ──► partial/final transcript events
      │                                  │
      ├────────► acoustic policy         ├────────► speculative semantic task
      │               │                  │                     │
      │               └── cancel/yield ──┼──────► quarantine ──┤
      │                                  │                     ▼
      └──────────────────────────────────┴────────► validation + policy gates
                                                               │
                                  action acknowledgments ──────┤
                                                               ▼
                                                    streaming TTS + playback
```

Concurrency removes avoidable waiting; it does not remove information dependencies. A response cannot be safely selected before enough caller intent exists, and speech cannot begin before enough response content is verified. These are the two causal gates.

## Research questions

### RQ1 — Latency

How much does stable-partial speculation reduce end-of-speech-to-first-audio at p50 and p95 compared with an otherwise identical streaming cascade?

### RQ2 — Semantic risk

How often does speculation begin from a partial transcript whose final meaning changes? How often is work cancelled, and how often does incorrect speech escape quarantine?

### RQ3 — Interaction quality

Does the interruption-repair state machine reduce inappropriate silence, repeated answers and talking over the user compared with playback cancellation alone?

### RQ4 — Task and trust

Do grounding and capability gates preserve task completion while reducing unsupported property claims and fake action confirmations?

### RQ5 — Portability

Do the gains hold across browser/WebRTC, SIP and PSTN transports, English and code-mixed Indian speech, and hosted versus open-weight speech components?

## Required baselines and ablations

| Variant | Stable-partial work | Final semantic check | Repair state | Ground/action gates |
|---|---:|---:|---:|---:|
| A. Sequential cascade | No | N/A | No | Yes |
| B. Concurrent streaming | No | N/A | No | Yes |
| C. Unguarded speculation | Yes | No | No | Yes |
| D. Guarded speculation | Yes | Yes | No | Yes |
| E. Guarded + repair | Yes | Yes | Yes | Yes |
| F. Complete Duet | Yes | Yes | Yes | Yes, with action acknowledgments |

Where feasible, compare the modular system against an open-weight native-duplex model such as PersonaPlex. The comparison must use the same task, knowledge, audio conditions and human-rating protocol; otherwise architecture and capability are confounded.

## Evaluation contract

### Latency

- end of caller speech → first audible agent audio, p50/p95;
- partial stability → speculative start;
- final transcript → semantic validation;
- LLM time to first usable clause;
- TTS time to first audio and browser jitter-buffer delay;
- caller speech start → agent playback yield.

### Conversation

- false barge-in rate;
- interruption yield success;
- inappropriate overlap / Takeover Rate;
- clarification appropriateness;
- repeated or stale response rate;
- abandoned and successfully repaired turns.

### Intelligence and safety

- task completion and qualification-field accuracy;
- factual grounding and source coverage;
- unsupported investment, scarcity, legal or inventory claims;
- false action-completion claims;
- consent and opt-out failures;
- sensitive-trait inference violations.

### Human experience

- blind naturalness and intelligibility ratings;
- perceived listening, empathy and control;
- preference against the sequential baseline;
- confidence intervals and inter-rater agreement.

The recent [Full-Duplex-Bench v3](https://arxiv.org/abs/2604.04847) and [tau-Voice](https://arxiv.org/abs/2603.13686) results reinforce why task success and interaction quality must be measured together. A voice system can sound fluid while losing grounded task capability, or complete the task while feeling unusably rigid.

## Minimum evidence for publication

Do not submit or advertise a paper until the project has:

- a frozen protocol and preregistered primary metrics;
- consent-cleared, de-identified real audio covering accents, noise and interruptions;
- at least the six ablations above on identical inputs;
- an open or reproducibly accessible baseline;
- blind human evaluation with enough raters for uncertainty estimates;
- failure taxonomy and negative results;
- cost and hardware disclosure;
- data-rights and ASBL authorization review;
- repeatable scripts from a clean environment.

An engineering report and open benchmark can precede a peer-reviewed paper. That is the recommended first publication: make the state machine, traces, eval fixtures and negative findings useful to other builders, then let empirical results determine whether a stronger research claim is justified.

## Open-source artifact plan

1. Extract provider-neutral interfaces for streaming ASR, semantic planner, TTS, actions and transport.
2. Publish the event schema and reference state machine.
3. Add an Asterisk SIP adapter and keep the browser adapter as the zero-cost path.
4. Wire every live session to Langfuse, Prometheus, Loki and Postgres with configurable transcript redaction.
5. Freeze a real-estate task suite and an acoustic interruption suite.
6. Implement the ablation switchboard so every architectural claim can be turned off independently.
7. Publish results, recordings with explicit rights, costs and failures.

## What would falsify the thesis

The thesis fails if guarded speculation does not materially improve latency, if semantic cancellations are frequent enough to waste cost, if wrong speech escapes often enough to damage trust, or if a simpler well-tuned streaming cascade matches human preference. Those outcomes are valuable and should be published rather than hidden.
