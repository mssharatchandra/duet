# India voice-AI market brief: an ASBL-first wedge, not another generic platform

**As of 23 August 2026.** Prices and capabilities change quickly; links are primary vendor or regulator
sources where possible. Vendor performance statements are labelled as claims, not independent facts.
This is product research, not legal advice.

## Recommendation in one sentence

Start as **an auditable multilingual real-estate revenue concierge that qualifies, educates and converts
first-party enquiries into site visits using RERA-approved facts and connected CRM workflows**. Prove it
inside ASBL before considering a horizontal platform.

Competing broadly with ElevenLabs, Bolna, Giga, Gnani, Retell or Vapi would make Duet one more orchestration
option in a fast-moving market. The defensible asset is narrower: consented Indian real-estate conversations,
an objection and interaction eval suite, reliable interruption/handoff, code-mixed speech performance,
RERA-grounded claim controls, Indian telecom operations and measured site-visit outcomes.

## How large is the opportunity?

There is no trustworthy public number for “Indian production voice-agent TAM” precise enough to use as a
fact. Do not present the entire BPO/BPM market as capturable voice-AI revenue.

- NASSCOM describes India's BPM sector at approximately **$49 billion in FY24**. This is an adjacent labor
  and workflow pool, not Duet's TAM. [NASSCOM](https://community.nasscom.in/index.php/communities/nasscom-insights/bpm-shifting-gears-shaping-tomorrows-skills-and-careers)
- IBEF estimates the broader Indian IT/BPM industry at **$315.4 billion in FY26**. Again, this is context,
  not an addressable voice-agent market estimate. [IBEF](https://www.ibef.org/industry/indian-it-and-ites-industry-analysis-presentation)

The correct bottom-up ASBL market calculation is operational:

```text
eligible first-party leads/month
× contact rate
× consented conversations
× minutes/conversation
× current fully-loaded cost/minute
× automation-assistable share
```

Then value the upside from faster first response, more consistent qualification, sales-agent capacity and
site-visit conversion. The experiment is attractive even if the global TAM narrative is wrong: an internal
system that improves cost per qualified visit has standalone value and produces the data needed for a
credible external product decision.

## Competitive landscape

Public list prices are not fully comparable: some include orchestration only, some include models, and
telephony/LLM charges are often separate.

| Provider | Public positioning / price signal | Implication for Duet |
|---|---|---|
| ElevenLabs | Conversational AI plus leading voice; $0.08 per additional agent minute, with LLM/telephony treatment described separately | Quality/reliability benchmark; do not try to win by TTS alone. [Pricing](https://elevenlabs.io/pricing/agents) |
| Bolna | India-oriented voice-agent platform; standard public price $0.06 / ₹5.52 per minute | Strong direct build-vs-buy baseline for Indian deployments. [Pricing](https://www.bolna.ai/pricing) |
| Giga | Enterprise support automation; AWS Marketplace lists $1 per processed call | Enterprise outcome model, not directly minute-comparable. [AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-okya4n4trkswi) |
| Gnani.ai | Indian multilingual enterprise voice automation; no simple standard public price found | Important enterprise/India benchmark; request a scoped quote rather than inventing a comparison. [Gnani](https://www.gnani.ai/) |
| Retell AI | Usage range publicly shown around $0.07–$0.31/minute depending on components | Good API-first benchmark for latency, testing and telephony UX. [Pricing](https://www.retellai.com/pricing) |
| Vapi | Platform fee shown around $0.05/minute, excluding chosen providers | Demonstrates modular orchestration economics; total cost needs all downstream providers. [Pricing](https://vapi.ai/pricing) |
| Sarvam | Indian speech primitives; STT ₹30/hour and Bulbul v3 ₹30/10k characters on the cited page | Makes an India-first custom cascade economically plausible, but integration/reliability becomes our burden. [Pricing](https://docs.sarvam.ai/api/getting-started/pricing) |
| LiveKit | Open-source/media and agent framework with self-hosting options | Useful transport/runtime substrate; Duet should differentiate above media plumbing. [Agents](https://docs.livekit.io/agents/) |

Selected scale/quality numbers are **vendor claims**, useful only as aspiration:

- Giga says resolution improved from 60% to 98% and cites support for 99 languages.
  [Vendor announcement](https://giga.ai/news/series-a)
- Gnani's site claims 30 million daily interactions, 200+ enterprises and sub-200 ms p95 latency.
  [Vendor site](https://www.gnani.ai/)
- ElevenLabs says its enterprise conversational platform handles more than five million conversation hours
  per month. [Vendor page](https://elevenlabs.io/agents/enterprise-conversational-ai)

None of these validates Duet's current quality. We need our own blind, replayable measurements.

## Why real estate is a good wedge

Real-estate sales calls combine the hard parts of applied voice AI in one bounded domain:

- facts must be current and attributable;
- buyers interrupt, compare, hesitate and code-switch;
- the agent must persuade without fabricating scarcity, returns or legal certainty;
- high-intent actions—brochure, callback, site visit—are measurable;
- human handoff is natural and economically valuable;
- ASBL has domain experts, internal workflows and a consented source of evaluation feedback.

That creates a better learning loop than a generic “Jarvis.” We can measure whether the agent understood,
stayed factual, created the correct action and improved a business outcome.

## Positioning

Avoid: “the cheapest AI caller” or “a human replacement.” Those invite a commodity comparison and create
trust/regulatory risk.

Use:

> **Duet is an auditable multilingual revenue agent for Indian real estate. It listens without losing the
> thread, grounds every project claim, respects consent, and hands qualified intent to the sales team.**

The initial buyer is ASBL's sales/technology leadership. The initial user is a first-party lead who has
requested information. The initial job is not closing an apartment autonomously; it is improving response,
education, qualification and site-visit coordination while preserving a human escalation path.

## Build versus buy

Build the parts that become differentiated evidence:

- interaction/turn state machine and interruption repair;
- real-estate policy and grounded-claim layer;
- ASBL knowledge/action contracts;
- conversation, audio and business-outcome evals;
- observability/correlation and operator QA;
- multilingual/code-mix behavior tuned to the actual customer distribution.

Buy or adopt commodity layers until measurement proves they block the outcome:

- Sarvam or another measured ASR/TTS provider;
- Gemini or another fast measured reasoning model;
- LiveKit/Asterisk/telephony transport rather than writing an SFU or PBX;
- Postgres, Langfuse, Prometheus, Grafana, Loki and Alloy rather than bespoke observability backends.

Open weights remain an important research track and fallback leverage, but “open” is not automatically
cheaper after GPU, operations, scaling and quality failures. Run a three-way eval—hosted best, open cascade,
native duplex—and promote a component only when it wins the relevant quality/latency/cost gate.

## Regulatory and trust boundary

- TRAI defines unsolicited commercial communication and maintains preference/consent mechanisms.
  [UCC overview](https://trai.gov.in/what-spam-or-ucc), [consent management](https://www.trai.gov.in/manage-your-consent)
- The 2025 TCCCPR amendment is relevant to commercial communications and should be reviewed with ASBL's
  telecom/legal owners before outbound production. [TRAI regulation PDF](https://www.trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf)
- India's DPDP Act/rules create obligations around notice, purpose, security, retention and rights; obtain
  current counsel before storing recordings or using calls for model training.
  [MeitY DPDP materials](https://www.meity.gov.in/documents/act-and-policies/digital-personal-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit)
- Telangana RERA and Real Estate Act Section 12 matter because misleading project advertising creates real
  liability. Treat approved facts and versioned sources as code.
  [TG RERA](https://rera.telangana.gov.in/54673hgsjkfdhgsfg-TG-RERA-lfkdbnklh5409u569),
  [India Code Section 12](https://www.indiacode.nic.in/show-data?actid=AC_CEN_17_19_00033_201616_1517807328405&orderno=12&sectionId=8636&sectionno=12)

Hours of sales recordings may be valuable for evaluation and post-training only if ASBL can establish lawful
purpose/notice/consent, access control, retention and de-identification. Do not dump noisy historical calls
into training. First inventory rights, diarize, redact, sample, label failure modes and reserve a customer-level
holdout. Prove English first because it narrows variables; collect multilingual/code-mix evals in parallel so
the architecture does not become English-only.

## Proposed operating targets

These are Duet's proposed gates, not established industry standards:

- 0 calls without a valid consent basis;
- 0 false project/RERA claims in the release eval;
- 0 fabricated tool confirmations;
- verified barge-in to silence under 250 ms p95;
- speech-end to first audible response under 1.2 s p95;
- tool execution success above 99%, with unknown outcomes reconciled;
- no reduction in qualified-lead/site-visit conversion before autonomous expansion;
- human escalation always available during the controlled pilot.

## 18-month route

### 0–3 months: evidence before autonomy

- establish ASBL consent/data/legal boundary and approved fact source;
- shadow or employee-only calls; baseline human funnel and cost;
- build 50–100 scenario eval plus consented phone-band audio fixtures;
- integrate sandbox CRM/site-visit tools and operator audit;
- finish isolation, load, failure and security work in `PRODUCTION_READINESS.md`.

### 3–6 months: controlled English pilot

- randomized assisted pilot on first-party leads;
- measure contact, qualification, advisor handoff, site visit, complaints and cost;
- keep humans in the loop for sensitive claims and uncertain actions;
- publish failures internally, not just aggregate wins.

### 6–12 months: multilingual reliability

- enable Telugu/Hindi/code-mix only after separate ASR, reasoning, TTS and human trust gates;
- add provider failover, telephony resilience and operational QA sampling;
- expand traffic only while conversion, factuality and complaint SLOs hold.

### 12–18 months: decide product versus internal advantage

- recruit two or three non-competing design partners only if ASBL evidence transfers;
- open-source the event contracts, orchestration controls and eval harness without customer data;
- commercialize managed telecom, compliance, integrations and reliability if those are the repeated pain;
- remain an internal product if external sales distract from a stronger ASBL advantage.

## Investment thesis, stated honestly

India's large BPM sector, multilingual complexity and expensive human call operations make production voice
AI worth a disciplined experiment. That does not imply a billion-dollar company automatically exists. The
falsifiable thesis is: **a domain-grounded, consent-safe voice system can lower cost per successful qualified
real-estate outcome while maintaining or improving trust and conversion.** Duet should earn the right to a
larger market narrative by proving that result in-house.
