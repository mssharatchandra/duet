# Aira first human trial: failure review and corrective design

**Trial date:** 23 August 2026  
**Verdict:** useful engineering evidence, failed naturalness acceptance  
**Source:** the user's exported conversation transcript

## What the trial proved

The stack could disclose its AI identity, request permission, stream speech, answer basic Broadway
questions and accept interruption. It did not yet behave like a thoughtful property expert. The
important lesson is that voice naturalness is a systems property: a good voice model cannot repair
incorrect endpointing, stale reasoning, repetitive dialogue policy or untruthful tool claims.

## Failure ledger

| Observed behavior | Root cause | Corrective control | Regression evidence |
|---|---|---|---|
| Sentence endings sounded rushed and details were lost | Bulbul pace 1.05 and temperature 0.55 | Priya, pace 0.94, temperature 0.72; punctuation-driven breathing | TTS configuration test |
| “Hmm” and “Okay” launched a new pitch | Lexical meaningfulness was mistaken for conversational intent | Backchannel classifier waits without an LLM call | Trial backchannel unit/flow tests |
| “Actually” became its own turn | Provider VAD ended an acoustic segment before the thought was complete | 2.1-second discourse-fragment grace | Turn-assembler regression |
| Aira stopped randomly | Any meaningful partial could cancel speech, including echo and continuers | Conservative semantic barge-in plus likely-echo rejection | Barge-in regression and real smoke test |
| Two agent replies ran together | Concurrent model replies had no generation ID; UI reused one line | Stale-result suppression and utterance IDs | Request metadata and UI protocol |
| Every route led to brochure/advisor | Prompt rewarded handoff as the safest next action | Advisor only for live/authorised facts or explicit request | 17-scenario reasoning eval |
| Privacy was repeated three times | No repetition policy and weak value architecture | Recent-response similarity gate and needs-to-value response shape | Repetition regression |
| “I will send/arrange/share” despite no integration | Language model confused intent with execution | Idempotent local/internal action adapter; accepted and completed are distinct | Action and capability regressions |
| Family/timeline evidence disappeared | Latest per-call score replaced prior conversation state | Monotonic explicit-evidence memory with quotes | Live trace state |
| ASBL became ASP | Proper-noun ASR substitution | Narrow domain correction, with raw transcript retained | Domain-normalization regression |
| Reasoning panel implied chain-of-thought | UI exposed an opaque generated sentence without provenance | Safe trace: intent, stage, evidence, facts, policy and timing | Source-linked interface |

## Aira's new conversational contract

Aira is a calm, candid Hyderabad property host—not a closer. It first acknowledges the caller's
actual words, then selects one verified differentiator, then explains why that matters to the
caller's stated need. It may ask one question, but a question is not mandatory. It can admit a
trade-off and can disqualify Broadway when the fit is poor.

Evidence-based persuasion for a family buyer should develop Broadway as a combination rather than
repeat a slogan:

1. privacy-oriented planning through private foyers and avoided opposite doors;
2. spacious 3/3.5-BHK layouts, curtain-wall light and published height;
3. Financial District location and ORR-corridor access;
4. 75% open space and more than 107,000 sq ft of indoor amenities;
5. a real trade-off: public pricing starts around INR 3 crore and possession is published for
   December 2029, both of which the buyer must judge against alternatives.

This is persuasive because it makes the value legible. It is not pressure, hidden psychological
profiling, a return promise or a claim that ASBL is universally “best.”

## Where answers come from

The language model is not allowed to browse freely during the call. It receives a versioned fact
registry built from:

- the [official ASBL Broadway project page](https://asbl.in/broadway/);
- the [official Broadway landing page](https://asbl.in/broadway/landing/apartments-for-sale-in-hyderabad/);
- the supplied Ajitesh Korupolu Broadway keynote transcript.

Every generated answer returns zero to three fact IDs. The server resolves only allowlisted IDs and
shows the claim, source and freshness rule in the browser. Volatile fields such as live inventory,
unit-specific pricing, offers and payment schedules remain human-authorised boundaries.

## What the interface reveals—and what it does not

For every accepted turn, the page now shows:

- raw and domain-normalized ASR text;
- whether Duet is hearing, waiting for continuation, deciding, guarding or speaking;
- public conversation stage, intent and response strategy;
- exact caller evidence retained for use case, budget fit, decision role and timeline;
- fact IDs, official source links and freshness requirements;
- action/capability policy result;
- turn-assembly, reasoning and speech-first-audio latency;
- whether speech finished, was interrupted or was suppressed as stale.

It does not show private chain-of-thought. A trustworthy production system needs decision
provenance and reproducible policy outcomes, not private model deliberation.

## Acceptance status

- Local code and flow tests: **131 passing**.
- Live reasoning eval after multi-action support: **132/136 checks, 97.1%**, 17 scenarios; the
  brochure-plus-callback action case passed and one final scenario hit a provider 429.
- Scripted real-service controlled-duplex flow: **passing**.
- Rich-turn latency: **2,715 ms median across three smoke runs**; this fails the market-competitive gate.
- Second human acoustic trial: **open**.
- Blind naturalness score, inappropriate-takeover rate, real-mic ASR WER and production telephony:
  **not yet measured**.

The build is ready for another local trial. It is not yet justified to call it world-class or
production-ready.
