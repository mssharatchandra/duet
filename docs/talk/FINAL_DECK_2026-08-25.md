# Humanising Voice AI

Final presentation source for the 25 August 2026 engineering talk. The visible slides are intentionally
minimal; the notes carry the technical depth. Claims labelled “measured” come from this repository.
Vendor numbers remain labelled as vendor claims because their latency definitions are not comparable.

## Visual system

- 16:9, warm cream paper with cyan halftone landscapes supplied by Sharat.
- Ink: deep navy `#102A43`; accent cyan `#288DC1`; caution coral `#D96C5F`; success teal `#268C82`.
- Headings: DM Sans or Manrope, semibold. Numbers: IBM Plex Mono. Body: Inter.
- Maximum 20–30 visible words on most slides. Use one diagram, chart, or sentence—not dashboards of text.
- Alternate the four landscapes. Add a translucent cream panel only when contrast requires it.
- Cite sources in a small footer. Put qualifications in speaker notes, not in microscopic body text.

## Narrative arc

Hook with a real conversation. Teach the audience how a voice agent works. Show why a cascade feels
slow even when each model is “fast.” Introduce Duet as a concurrent control system. Walk through the
experiments—especially the failed ones—and show how evals changed our decisions. End with an India-first
business wedge and a production programme, not a claim that the prototype is finished.

---

## Slide 1 — Humanising Voice AI

**Visible**

Duet / Aira

*A month of building, breaking and measuring a real-time voice agent.*

**Visual**: Full-bleed mountain background. Small waveform crossing the horizon.

**Speaker notes**: Start with the human experience, not the architecture. Ask: can an AI sales agent actually
listen? We tried to build an empathetic ASBL
Broadway sales concierge that could understand an Indian caller, answer from verified facts, take actions,
and stop when interrupted. The important artifact is not a perfect bot. It is the evidence about what makes
voice systems feel human—and what makes them fail.

---

## Slide 2 — A voice agent is a real-time control system

**Visible**

Listen · decide · speak · yield · remember · act

All at once.

**Visual**: A disciplined control-loop diagram: one shared conversation-state band, then Listen → Decide → Speak,
with Remember, Yield and Act visibly running beside every turn.

**Speaker notes**: A voice agent is not “an LLM with a microphone.” It is a timing-sensitive distributed
system. It must continuously ingest audio, estimate who owns the floor, maintain state, retrieve facts, decide
whether speech is safe, synthesize audio, and remain cancellable. Human-likeness is system behaviour, not a TTS
voice setting.

---

## Slide 3 — Demystifying the jargon

**Visible**

| Term | What it literally means | In a conversation |
|---|---|---|
| VAD | Voice Activity Detection | Is someone speaking? |
| ASR / STT | Automatic Speech Recognition / Speech-to-Text | What did they say? |
| EOU | End of Utterance / endpointing | Are they finished? |
| LLM TTFT | Large-language-model time to first token | When does thinking begin? |
| TTS TTFB | Text-to-speech time to first byte | When can speech begin? |
| Barge-in | Interruption detection and recovery | Can the caller take the floor? |
| RTF | Real-time factor | Can inference keep up with speech? |

**Visual**: A three-column glossary: acronym, literal technical meaning, then the plain-English question it answers.

**Speaker notes**: Clarify three easily confused latency clocks. ASR model processing is not the same as
endpointing delay. LLM time-to-first-token is not total response completion. TTS time-to-first-byte is not
total synthesis time. The listener experiences the composition plus transport and jitter buffering.

---

## Slide 4 — The waterfall tax

**Visible**

speech end → endpoint → ASR → reasoning → TTS → playback

`wait + wait + wait + wait`

**Visual**: A single horizontal waterfall with additive coloured bars.

**Speaker notes**: In a naïve cascade, each stage waits for the previous stage to finish. Even respectable
components produce an awkward pause when their tails add. In Duet’s first rich-response measurement the median
was 2,715 ms: roughly 623 ms turn assembly, 1,739 ms complete reasoning, and 443 ms TTS first audio. That failed
our own latency gate.

**Source**: repository Decision 0021 and `docs/LATENCY_ARCHITECTURE.md`.

---

## Slide 5 — Fast models do not guarantee a fast conversation

**Visible**

The latency budget has four owners:

`turn timing`  `reasoning`  `speech start`  `playout`

**Visual**: Four latency owners with the handoff each must wait for. Beneath them, the actual safety-boundary
chain: caller finished → meaning stable → safe first clause → playable audio.

**Speaker notes**: Optimize the user-perceived interval: end of caller intent to audible first agent audio.
Measure p50 and p95. Then pair latency with wrong-start rate, takeover rate, factuality and task success. A fast
answer that starts before the user finishes is not low latency; it is an interruption defect.

---

## Slide 6 — Duet’s thesis: guarded speculative duplex

**Visible**

Start safe work early.

Commit only when meaning is stable.

Cancel everything stale.

**Visual**: A partial transcript branching into a quarantined speculative lane, then rejoining at “final meaning
confirmed.”

**Speaker notes**: Duet is not a new monolithic foundation model. It is a modular asynchronous architecture.
Stable partial transcripts may start retrieval and reasoning. Results remain quarantined until the final
transcript preserves meaning. Deterministic policy can pre-empt generation. Every generation and audio buffer
carries cancellation state. This is our candidate engineering contribution; concurrency itself is prior art.

---

## Slide 7 — Concurrent lanes, causal gates

**Visible**

```text
LISTEN ─────────────────────────────────────►
TURN       partial ── stable ── final
POLICY  consent · opt-out · barge-in · claims
PLAN             retrieval · reasoning ─────►
ACT                         tool request ───►
SPEAK                 safe clause ── audio ─►
```

**Visual**: Swimlane timeline, not five boxes in a row.

**Speaker notes**: The lanes run concurrently, but information dependencies still exist. We need enough stable
intent before selecting an answer, and enough verified content before speech. The architecture removes unnecessary
waiting without pretending causality disappears. ASR remains armed while TTS plays so interruption can cancel
speech immediately and create a new conversational state.

---

## Slide 8 — What runs inside Aira

**Visible**

Browser audio → Sarvam Saaras → Duet controller → Gemini → Sarvam Bulbul → speaker

Around it: policy · facts · actions · telemetry

**Visual**: Central controller with five event connections; policy ring outside it.

**Speaker notes**: Browser audio is streamed continuously. Saaras v3 Realtime provides partial/final transcripts
and speech events. Duet assembles turns, owns consent, barge-in, stale-response suppression and capability checks.
Gemini Flash Lite plans grounded responses. An action adapter records or calls brochure, callback, CRM and
site-visit tools. Bulbul v3 uses a pre-warmed persistent WebSocket. The local demo planner is a quota-independent
fallback—not the production intelligence path.

---

## Slide 9 — Live demo

**Visible**

LIVE

**Visual**: Empty 16:9 video frame with a thin cyan keyline over the arch background. No other content.

**Speaker notes**: Insert the recorded Aira demo here. Show: disclosure and permission; one project question;
one interruption; one brochure or site-visit action; the visible decision trace. Do not improvise with a live
cloud model tomorrow. The recording path uses the local grounded demo planner so Gemini quota cannot break it.

---

## Slide 10 — Speech quality is product quality

**Visible**

If ASR misses the need, reasoning solves the wrong problem.

If TTS rushes the answer, correct reasoning still feels wrong.

**Visual**: Two large waveforms labelled “meaning in” and “trust out.”

**Speaker notes**: Our first prototype sounded robotic because multiple defects compounded: a 16 kHz/24 kHz
audio bug, synthetic voice artifacts, rushed pace, endpoint clipping, and a planner repeatedly pushing the same
next step. Sarvam improved our real Indian-English captures and provides true streaming events, code-mix support,
and a coherent Indian speech plane. It is not open weights; provider portability remains intentional.

**Source**: Sarvam Saaras v3 and Voice Agents documentation; repository Decisions 0009, 0017, 0020.

---

## Slide 11 — The ASR eval changed the answer

**Visible**

WER at 5 dB noise ↓

`base.en 14.1%`  `small.en 8.7%`  `MLX Whisper 3.4%`  `Parakeet 2.7%`

In a noisy call, ASR choice determines what the agent believes before reasoning begins.

**Visual**: Four descending bars, one highlight on Parakeet, plus one operational takeaway below the chart.

**Speaker notes**: The first clean synthetic eval was too easy and could not discriminate. We added seeded noise,
reverb, speed perturbation and clipping. The ranking then became clear and even reversed an earlier decision.
Parakeet was also 0.04–0.08× real-time under contention, giving much more headroom. Limitation: synthetic Piper
speech is still off-distribution; real microphone captures remain the acceptance set.

**Source**: `eval/asr/README.md`, 30 utterances × 7 conditions, Apple M5.

---

## Slide 12 — TTS: optimize the clock people hear

**Visible**

Time to first audio

`Piper 83 ms`  vs  `Kokoro 380 ms`

But voice quality still needs human listeners.

**Visual**: Two start markers on a 500 ms timeline.

**Speaker notes**: Both engines synthesize faster than real time, so throughput was not the issue. TTFB lands
directly on the critical path in a cascade. But speed alone is not quality: Piper was fast and sounded robotic.
Human MOS/preference tests are required. Sarvam’s warm persistent TTS measured 223 ms first audio in our real
path and sounded more appropriate for Indian-English conversation.

**Source**: `eval/tts/README.md`, repository Decision 0022.

---

## Slide 13 — Why Gemini won our reasoning gate

**Visible**

Not “the best LLM.” The best measured trade-off in this experiment.

| Model | First-plan latency | Evidence level |
|---|---:|---:|
| Qwen 0.8B | 153 ms | 0 — fabricated facts |
| Gemma 1B | 760–1,750 ms | 0 — schema/policy failures |
| Qwen 4B | 1,623 ms | 1 — relevant, ungated |
| Gemma 4B | 2,858–3,142 ms | 2 — grounded sample |
| Gemini Flash Lite | 1,120 ms | 3 — 132/136 checks |

**Visual**: Scatter plot with first-plan latency (0–3,200 ms) on the x-axis and the grounding/policy evidence
we actually collected (0–3) on the y-axis. It is explicitly not a universal model-quality benchmark.

**Speaker notes**: Use precise language. Gemini 3.1 Flash Lite is designed for low-latency, high-frequency
workflows and supports structured outputs and function calling. In our 17-scenario reasoning eval the richer
path reached 97.1% checks. It remained the largest latency component and its free-tier quota broke a recording,
so we added a deterministic fallback. The y-axis is deliberately an evidence scale—not a fabricated quality score:
0 means a known control failure, 1 relevant but not gated, 2 a grounded sample, and 3 the 17-scenario eval.
“Best” here means among the models and policy traps we measured, not a universal frontier ranking.

**Source**: Google Gemini 3.1 Flash Lite docs; repository Decisions 0021–0022 and local model measurements.

---

## Slide 14 — Local reasoning: the speed–reliability wall

**Visible**

| Model | First-plan latency | Result |
|---|---:|---|
| Qwen 0.8B | 153 ms | fast, invented facts |
| Qwen 4B | 1,623 ms | relevant, too slow |
| Gemma 1B | 760–1,750 ms | schema/policy failures |
| Gemma 4B | 2,858–3,142 ms | grounded, slower than Gemini |
| **Gemini Flash Lite** | **1,120 ms** | **132/136 grounded-policy checks · chosen** |

**Visual**: Five-row decision table. Gemini is highlighted as the selected reference line.

**Speaker notes**: Local is attractive for privacy, predictable cost and owned KV caching. But a smaller model
that violates a financial-claim guard is not a viable sales brain. A larger local model that is slower than the
API has no latency ROI on this laptop. Gemini was selected because it combined an observed 1,120 ms plan with
132/136 grounded-policy checks and structured tool support. Re-evaluate local candidates on production GPU
hardware; do not generalize this Apple M5 result into “local models are bad.”

**Source**: local model measurements; repository Decisions 0021–0022.

---

## Slide 15 — Moshi proved speed—and failed control

**Visible**

| | Handoff p50 | Takeover | Overlap |
|---|---:|---:|---:|
| Moshi duplex | **240 ms** | 0.24 | 0.234 |
| Cascade | 1,880 ms | **0.00** | **0.053** |

**Plain-English takeaway**: It answered quickly, but often spoke at the wrong time.

**Visual**: A trade-off line: fast ↔ polite.

**Speaker notes**: Moshi models caller and agent audio as parallel streams and has roughly 200 ms practical
latency in its paper. On our 10-scenario benchmark it was eight times faster at the median and produced
backchannels. It also grabbed the floor and rambled. Its p95 was 3.25 seconds. We benched it as the default
product path because controllability and clarity mattered more than a median latency win.

**Source**: Kyutai Moshi paper; `eval/bench/RESULTS.md`.

---

## Slide 16 — Experiment 1: earlier speculation did not prove speed

**Visible**

**The thesis**: start reasoning after two stable words rather than wait for four.

**What we expected**: a meaningfully earlier spoken reply.

**Measured A/B**: `1,943 ms` vs `1,912 ms` — a 31 ms difference across two live runs.

**Plain-English takeaway**: the change worked technically, but the measured difference was too small and the sample too small to call it faster.

**Visual**: a clean thesis → expectation → measurement → honest verdict flow.

**Speaker notes**: PR #1 lowered the stable-partial floor from four words to two while preserving opt-out,
ambiguity and semantic-confirmation gates. The mechanism fired correctly, but n=2 live runs could not separate
the 31 ms gap from normal variance. Gemini explicit cache storage was unavailable on the free tier, and implicit
caching did not engage. We recorded the negative result rather than claiming a win.

**Source**: GitHub PR #1, “Widen speculative-reasoning coverage to short turns.”

---

## Slide 17 — Experiment 2: the proxy win inverted

**Visible**

Proxy: `4.9× fewer free-run tokens` ✓

Reality: `+59% takeovers` · `+41% overlap` · `8× worse handoff` ✕

**Plain-English takeaway**: we made the bot wait less; it then interrupted people more often.

**Eval rule**: *Eval the behaviour you care about—not the proxy that flatters your optimization.*

**Visual**: A green proxy arrow flipping into three coral real-metric arrows.

**Speaker notes**: PR #2 used a local KV-cached brain and shortened Moshi’s quiet window. The first proxy looked
spectacular. A real turn-taking A/B showed the “fast” configuration was ruder on every important metric. The
quiet window was protective, not wasted latency. An even earlier 0.00-token result failed to reproduce due to
state leakage in the harness. This is the talk’s key scientific lesson: eval the behaviour you care about, not
the proxy that flatters your optimization.

**Source**: GitHub PR #2, `docs/DUPLEX_STEERING.md`.

---

## Slide 18 — Evals are the new PRDs

**Visible**

Every failure becomes:

`scenario → metric → threshold → regression test`

**Plain-English takeaway**: live calls reveal failures a prompt cannot. We made each one a repeatable test.

**Visual**: Four-step loop ending back at “real call.”

**Speaker notes**: We built deterministic unit tests, 17 grounded-reasoning scenarios, augmented ASR WER, TTS
TTFB/RTF, turn-taking metrics, controlled barge-in smoke, container boot checks, and blind-human-eval protocols.
Examples from real failures became tests: “I changed my mind,” “wait a minute,” clipped yes/no turns, duplicate
actions, stale responses and opt-out. CI runs cheap deterministic gates on every commit; quota-consuming live
evals run manually or on schedule.

---

## Slide 19 — The model does not own trust

**Visible**

Deterministic code owns:

`consent`  `opt-out`  `claims`  `staleness`  `capabilities`

**Plain-English takeaway**: models can be wrong. They propose; deterministic code verifies consent, facts and permissions before speech or action.

**Visual**: A guardrail surrounding the reasoning model, with tool arrows passing through a capability gate.

**Speaker notes**: The LLM may propose an action. Only an action adapter may report accepted or completed. The
same principle applies to brochure, callback, CRM and site visit. A “request” is not “done.” Opt-out cancels
reasoning and speech immediately. Sensitive traits cannot drive lead scoring. Public product facts carry source
IDs. The UI exposes an inspectable decision trace—intent, evidence, policy, facts—not private chain-of-thought.

---

## Slide 20 — If you cannot replay it, you cannot improve it

**Visible**

Langfuse — replay model + tool decisions

Prometheus + Grafana — spot latency + error regressions

Postgres — join turns, actions + outcomes

JSONL / Loki — diagnose event-level failures

**Why it matters**: observability closes the loop—real failures become better eval cases before the next release.

**Visual**: One trace ID connecting four stores.

**Speaker notes**: Telemetry is asynchronous and never blocks audio. Every session shares a trace ID across
voice spans and the durable call record. Content is redacted by default. The latest four-minute demo produced 78
Langfuse observations, 11 user utterances, three playback cancellations and two accepted local actions. When a
trace reveals a failure pattern—an interruption miss, stale answer or action error—we turn that pattern into a
new eval scenario and regression test.

---

## Slide 21 — Latest Aira run: a replayable live session

**Visible**

`443 ms` median response start

`3` interruptions · `2` actions · `11` user turns

**Plain-English takeaway**: one trace connects responsiveness, interruptions, actions and the caller’s journey.

**Visual**: A minimal event timeline with three cancellation marks and two action diamonds.

**Speaker notes**: This run used Sarvam ASR/TTS plus the local grounded planner, so reasoning cost and latency
were zero. The 443 ms median is end-of-speech to first server audio, not browser-perceived latency. The point
is not a single headline number: this trace links response timing, three playback cancellations, two accepted
actions and 11 caller turns, making the conversation diagnosable and improvable.

**Source**: session `1787592808-61dd64`, Langfuse trace `9722afa5-8284-454f-a9cd-4400f69004d4`.

---

## Slide 22 — Aira vs Sarvam Voice Agents: honest comparison

**Visible**

| System | Number | What it means |
|---|---:|---|
| Aira local-plan run | 443 ms p50 | measured, one session |
| Aira Gemini path | 1.62–2.90 s | measured rich responses |
| Sarvam Voice Agents | <500 ms | vendor claim; definition unpublished |

**Visual**: Three bars with different hatch patterns and a large “not yet apples-to-apples” label.

**Speaker notes**: Sarvam now claims under 500 ms real-time latency and ₹3.50/min for its managed voice-agent
stack. Their docs explicitly say there is no official round-trip SLA in the component guide. We cannot call this
a benchmark yet. The fair test is identical scripts, network region, phone/WebRTC transport, 30+ calls,
speech-end-to-audible-audio p50/p95, takeover, task success, factuality, human preference and cost.

**Source**: Sarvam Voice Agents product page, launch docs and Epoch summary.

---

## Slide 23 — Why India is a voice market

**Visible**

`22 official languages`

`2M+ voice conversations/day` — Sarvam claim

`₹3.50/min` — managed agent price signal

`$6.3M seed` — Bolna, 2026

**Key takeaway**: The moat is not only a pretty voice: noisy telephony, dialects, interruption, cost, compliance, integrations and reliability at large volumes.

**Visual**: Four large numerals over the cloud background.

**Speaker notes**: India is voice-first, multilingual, code-mixed, mobile and operationally call-heavy. The
moat is not only a pretty voice: noisy telephony, dialects, interruption, cost, compliance, integrations and
reliability at large volumes. Sarvam reports more than two million voice conversations a day and is building a
full-stack sovereign platform. Bolna raised $6.3M to make deployment self-serve. These are market signals, not a
top-down TAM proof. Use in-house economics to validate the wedge.

**Source**: Sarvam Circle and Epoch; Bolna funding announcement; India Constitution language schedule.

---

## Slide 24 — The wedge: remove junk work, not humans

**Visible**

AI handles:

permission · intent · FAQs · qualification · follow-up

Humans handle:

trust · nuance · negotiation · closure

**Visual**: A lead funnel with “agent” at the wide top and “advisor” at the qualified bottom.

**Speaker notes**: Start with ASBL inquiry reactivation and qualification. Aira can disclose itself, ask whether
the caller wants a family home or investment, answer verified Broadway questions, collect timing and broad
budget, and request a brochure, callback or site visit. Success is not calls automated. It is advisor hours
saved, contact rate, qualified handoffs, factuality, opt-out compliance and incremental site visits.

---

## Slide 25 — Prototype → production voice system

**Visible**

`session isolation`  `telephony`  `DNC`  `human transfer`

`SLOs`  `load tests`  `replay`  `retention`  `incident response`

**Visual**: Nine small production “rivets” holding a single call line.

**Speaker notes**: Commercial systems win through operational maturity: carrier integrations, regional routing,
echo control, retries and circuit breakers, versioned prompts, campaign controls, abuse prevention, recordings
and deletion, quality sampling, on-call alerts and graceful human handoff. The current app is single-session and
browser-first. It is a strong instrument and demo, not yet an outbound production dialer.

---

## Slide 26 — A 90-day proof, not a frontier-model lab

**Visible**

1. English, one project, one workflow

2. Shadow → internal → consented pilot

3. Promote only on measured gates

**Visual**: Three stepping stones across the beach background.

**Speaker notes**: Week 1–3: instrument 100 historical, consent-safe scenarios and build the golden set. Week
4–6: connect real CRM actions and telephony in shadow mode. Week 7–9: small consented English pilot with human
takeover. Week 10–12: compare agent versus current operation on qualification yield, complaints, factuality,
latency, tool success and cost. Add Telugu/Hindi/code-mix only after separate speech and trust gates.

---

## Slide 27 — The lesson

**Visible**

Human is not a model.

Human is the behaviour of the whole system.

**Visual**: Mountain horizon with a tiny two-channel waveform converging in the centre.

**Speaker notes**: We started by searching for a magical full-duplex model. We ended with a more useful view:
natural conversation emerges from listening quality, timing, controllability, grounded reasoning, cancellable
speech, trustworthy actions and a relentless evaluation loop. Buy the best current speech and reasoning
primitives. Own the interaction state and evidence. Keep the research lane alive, but let production earn every
claim.

---

# Appendix

## A1 — Research map

- Moshi: native two-stream full-duplex speech model, theoretical 160 ms / practical ~200 ms.
- PersonaPlex: Moshi-based role and voice conditioning; evaluated with FullDuplexBench.
- FD-Bench: 293 simulated conversations and 1,200 interruptions across three open systems.
- Synchronization and Turn-Taking in Full-Duplex Speech Dialogue Models: controlled Moshi studies of noise and
  decoding bias.
- Duet: modular guarded speculation and capability-backed actions; novelty unproven until human ablations.

## A2 — Metrics that matter

| Layer | Metric |
|---|---|
| ASR | WER/CER by language, accent, SNR and code-mix |
| Turn | endpoint delay, false endpoint, takeover, overlap, barge-stop |
| Reasoning | factuality, policy pass, task success, TTFT |
| TTS | TTFB, MOS/preference, intelligibility, glitches |
| System | E2E p50/p95, error rate, cost/min, abandonment |
| Business | qualified handoff, advisor time saved, site-visit conversion |

## A3 — Questions to expect

- **Is this truly full duplex?** Current Aira is controlled duplex: it keeps listening during speech and can
  cancel. Moshi is the native full-duplex research lane.
- **Why not one speech-to-speech model?** Today it sacrifices inspectability, actions and deterministic policy in
  this use case. We keep evaluating it.
- **Why not a 20B local LLM?** Quality may improve, but the current laptop latency and contention do not meet the
  voice budget. Test on a production GPU with the same gates.
- **Can this call customers tomorrow?** No. Registered telephony, DNC persistence, per-call isolation, human
  transfer and a consented pilot are P0.
- **What is defensible?** Interaction state, eval data, domain workflows, reliability and the feedback loop—not
  commodity access to ASR, LLM or TTS.

## Sources for slide footers

- Moshi: https://arxiv.org/abs/2410.00037
- PersonaPlex: https://research.nvidia.com/labs/adlr/personaplex/
- FD-Bench: https://arxiv.org/abs/2507.19040
- Synchronization and Turn-Taking: https://arxiv.org/abs/2605.20356
- Gemini 3.1 Flash Lite: https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite
- Sarvam Voice Agents: https://www.sarvam.ai/products/voice-agents
- Sarvam announcement: https://docs.sarvam.ai/conversations/newly-launched
- Sarvam Epoch: https://www.sarvam.ai/epoch/summary
- Sarvam Saaras v3: https://www.sarvam.ai/blogs/asr
- Bolna funding: https://www.bolna.ai/newsroom/bolna-bags-63-million-seed-funding-led-by-general-catalyst-to-build-indias-voice-ai-platform
- Repository evidence: `docs/DECISIONS.md`, `eval/asr/README.md`, `eval/tts/README.md`,
  `eval/bench/RESULTS.md`, PR #1 and PR #2.
