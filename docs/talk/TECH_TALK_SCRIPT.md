# Duet technical talk — slide script

**Audience:** ASBL engineering leadership, experienced engineers, CTO and product stakeholders  
**Format:** 25–30 minutes plus a 3-minute live demo  
**Visual direction:** Steve Jobs-inspired restraint—black or warm-white canvas, one claim per slide, giant
type, one diagram only when causality requires it, no card-grid dashboards.  
**Communication job:** By the end, the engineering team should believe a small team can build a valuable,
production-measurable voice system without training a frontier model, while understanding exactly what is
working, what is not, and what ASBL should approve next.

The visible copy is intentionally sparse. The detail belongs in the spoken narrative and the live system.

## Slide 1 — Can an AI sales agent actually listen?

**Visible:**

> Can an AI sales agent actually listen?
>
> Duet · an ASBL voice-AI systems experiment

**Visual:** black field, white title, one subtle audio waveform.

**Talk:** Most voice bots can hear words. Far fewer can listen while they speak, recover when interrupted,
stay grounded in product truth and prove what happened. We set out to build that system—not merely connect
three APIs.

## Slide 2 — Demo before architecture

**Visible:**

> Ask. Interrupt. Change your mind.

**Visual:** full-screen browser demo. No architecture explanation yet.

**Demo script:**

1. Accept disclosure and permission.
2. Ask why Broadway is relevant for a hybrid-working family.
3. Interrupt during the answer: “Wait—privacy matters more.”
4. Ask one factual question.
5. Request a brochure/site visit; show the action result and correlated trace.
6. If the provider fails, use the recorded trace rather than improvising.

**Rule:** never claim the experience is perfect. Let the audience hear it.

## Slide 3 — Our first version sounded terrible

**Visible:**

> Accurate words are not a human conversation.

Smaller line:

> Robotic pace. Lost phrases. Late interruptions. Repetitive reasoning.

**Talk:** This was the important failure. The instinct was to blame the voice. The transcript showed four
different systems failures: ASR errors, endpoint delay, speech-buffer glitches and a planner optimized to
push the same next step. “Human” is not a TTS setting.

## Slide 4 — A voice agent is a real-time control system

**Visible diagram:**

```text
audio → turn → meaning → action → audio
  ↘ cancellation · consent · deadlines · evidence ↗
```

**Talk:** The LLM is one component. The call controller owns time, state and cancellation. Audio arrives
continuously. Partial words change. Tools can complete after a timeout. Speech already sent to a speaker
cannot be unsent. This is closer to distributed systems than chatbot UI work.

## Slide 5 — The five boxes are not a waterfall

**Visible:**

> Listen continuously.
> Speculate early.
> Commit carefully.
> Cancel everywhere.

**Talk:** ASR, policy, reasoning, action preparation and playback run as concurrent lanes. But concurrency
cannot remove two causal gates: we need enough stable caller intent to choose an answer, and enough verified
content to speak safely. We move work before those gates and make invalid work cheap to discard.

## Slide 6 — Guarded speculative duplex

**Visible diagram:**

```text
stable partial ──► speculative reasoning ──┐
                                          ├─ semantic match ─► speak
final transcript ─────────────────────────┘
                            mismatch ─► discard + replan
```

**Talk:** Duet begins reasoning when a partial transcript remains stable. It quarantines the result. The
final transcript either confirms the meaning or invalidates it. Deterministic policy can pre-empt both. This
is our candidate research contribution—but it is a hypothesis until ablations and human evaluation show a
gain without more wrong starts or factual failures.

## Slide 7 — Interruption is not a mute button

**Visible:**

> “Wait.”  ≠  “Stop calling.”  ≠  “Actually, what about privacy?”

**Talk:** First we yield the acoustic floor. Then we decide what the interruption means. A pause gets an
acknowledgment. Opt-out latches do-not-contact. A vague fragment asks for clarification. A complete question
supersedes stale reasoning. Every generation—including TTS buffers—carries cancellation state.

## Slide 8 — The model does not own trust

**Visible:**

> Consent. Claims. Actions. Opt-out.
>
> Deterministic gates outside the LLM.

**Talk:** Prompts are not a security boundary. Aira can persuade using approved project value, but it cannot
invent inventory, guaranteed returns or a successful CRM action. If ASBL's tool says `completed`, we can say
completed. If it says `requested`, we say requested. If uncertain, clarify or transfer.

## Slide 9 — What runs today

**Visible architecture:**

```text
Browser mic
  ├─ Sarvam Saaras v3     streaming ASR
  ├─ deterministic lane   consent + interruption + claims
  ├─ Gemini Flash Lite    grounded planning
  ├─ ASBL action adapter  idempotent requests
  └─ Sarvam Bulbul v3     persistent streaming TTS
        ↓
Browser speaker
```

Small footer: `controlled-duplex cascade · not a native speech model`

**Talk:** Hosted speech and reasoning let a CPU orchestrator run on a modest VPS. Open-weight alternatives
remain an eval track. We should not replace a component because it is fashionable; it must beat the current
one on the relevant latency, quality, cost and operating gate.

## Slide 10 — The honest numbers

**Visible:**

> 2.046 s
> final speech end → first audible response
>
> 288 ms
> synthetic barge-in → playback yield

Smaller line: `148 focused tests · human naturalness gate still open`

**Talk:** These are not industry-leading claims. Barge-in control is promising but missed our proposed
250 ms p95 target in this one run. Rich response latency is still too high and variable. A 300–400 ms
headline would be dishonest: endpointing plus TTS can consume that
budget before semantic reasoning. The near-term target is under 1.2 seconds p95 while preserving task success.

## Slide 11 — If you cannot replay it, you cannot improve it

**Visible:**

> One call ID. Four views.

```text
Langfuse  reasoning trace
Prometheus latency + errors
Loki      correlated events
Postgres  outcome + cost summary
```

**Talk:** Every live session now has a shared call and trace identity. Content is redacted by default.
Telemetry uses bounded queues and never blocks audio. We can move from “it felt slow” to the precise turn,
provider and generation that caused the delay.

## Slide 12 — A demo is not production

**Visible:**

> One call can impress you.
> One thousand calls will expose you.

**Talk:** Production requires per-call isolation, durable consent/DNC, provider circuit breakers, admission
control, tool reconciliation, telephony, security, load/chaos tests, canaries, rollback, alerts and an on-call
owner. Our Graphify map found the live Session as the largest coupling hub. We will extract it incrementally,
not throw away working cancellation logic in a heroic rewrite.

## Slide 13 — The India opportunity needs a wedge

**Visible:**

> Not another voice platform.
>
> An auditable multilingual revenue agent for Indian real estate.

**Talk:** India's roughly $49B FY24 BPM sector is context—not our TAM. We earn a market thesis by improving
one in-house outcome: cost per consented qualified site visit, with equal or better trust and conversion.
Real estate is a strong proving ground because facts, persuasion, code-mix, actions and compliance all matter.

## Slide 14 — Build the evidence. Buy the plumbing.

**Visible:**

> Build
> interaction · grounding · ASBL tools · evals
>
> Adopt
> speech · reasoning · media · observability

**Talk:** We should not train a frontier speech model to prove this product. Use Sarvam/Gemini/LiveKit or
Asterisk while they win. Build the interaction and domain controls that create proprietary evidence. Keep
open-weight and native-duplex systems as measured challengers, not ideology.

## Slide 15 — A 90-day proof

**Visible:**

> 1. Isolate every call
> 2. Connect consent + CRM + handoff
> 3. Build the ASBL eval set
> 4. Shadow first-party leads
> 5. Compare qualified site visits

**Talk:** Start employee-only, then assisted/shadow traffic. No autonomous broad dialing. Gate each expansion
on factuality, complaint rate, latency, tool success, conversion and cost. English first to reduce variables;
collect Telugu/Hindi/code-mix evaluation in parallel.

## Slide 16 — The real artifact is the learning loop

**Visible:**

> Confront reality.
> Measure the failure.
> Learn the system.
> Ship the next experiment.

Smaller close:

> How hard can it be?

**Talk:** We did not build a frontier lab. We built a system that lets a small team discover where frontier
quality actually comes from—and improve one measured failure at a time. The ask is a 90-day ASBL in-house
pilot with consented data access, sandbox tools and a small allowlisted lead cohort.

## Q&A backup — keep off the main stage unless asked

### Why not a local 20B model?

A 20B model may improve semantic quality, but on the current Mac it does not remove end-to-end latency; it
adds inference and operating burden. The local 4B test had ~1.6 s TTFT, while a 0.8B model was fast but
invented facts. Re-evaluate on a production GPU with the same grounding/latency suite.

### Why not native full duplex?

Moshi/PersonaPlex are important research baselines. Today the modular cascade gives ASBL inspectable text,
fact gates, tools and replaceable Indian-language speech. Native duplex becomes a candidate when it meets
domain grounding, voice, deployment and action-control requirements.

### How much cheaper can it be?

Unknown until measured. Public prices are not apples-to-apples, and self-hosted GPU utilization can erase
API savings. Optimize cost per successful site visit, not token or minute cost alone.

### Can historical calls train it?

Potentially, after rights/consent review, PII controls, diarization, quality sampling and a customer-level
holdout. Use them first for evaluation and error taxonomy; training comes later.

## Speaker-note sources

- Moshi: https://arxiv.org/abs/2410.00037
- PersonaPlex: https://arxiv.org/abs/2602.06053
- Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
- ElevenLabs testing: https://elevenlabs.io/blog/testing-conversational-ai-agents
- ElevenLabs OpenTelemetry traces: https://elevenlabs.io/docs/eleven-agents/customization/opentelemetry-traces
- NASSCOM BPM context: https://community.nasscom.in/index.php/communities/nasscom-insights/bpm-shifting-gears-shaping-tomorrows-skills-and-careers
- Sarvam pricing: https://docs.sarvam.ai/api/getting-started/pricing
- Bolna pricing: https://www.bolna.ai/pricing
- TRAI UCC: https://trai.gov.in/what-spam-or-ucc
- TG RERA: https://rera.telangana.gov.in/54673hgsjkfdhgsfg-TG-RERA-lfkdbnklh5409u569
- Repository measurements: `docs/DECISIONS.md`, Decisions 0022–0025.
