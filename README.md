# Aira: a guarded speculative-duplex real-estate voice agent

**An open-source systems experiment in making a streaming ASR → LLM → TTS agent interruptible, grounded, auditable and humane. The concrete demo is a real-estate sales concierge for ASBL Broadway.**

[Architecture](docs/ARCHITECTURE.md) · [Research direction](docs/RESEARCH_DIRECTION.md) · [Evaluation](eval/README.md) · [Decisions](docs/DECISIONS.md) · [Voice-AI learning guide](docs/blog/voice-ai-the-80-20.md)

> Project status, 23 August 2026: the local browser demo works with live Sarvam ASR/TTS and Gemini reasoning. It is a controlled-duplex, interruptible cascade—not a frontier end-to-end speech model and not production-ready. The latest synthetic real-service smoke measured 2.126 seconds from final speech end to first audible audio and 192 ms to yield playback after a synthetic barge-in. Human acoustic testing, multilingual evaluation, direct live-session telemetry and telephony remain open gates.

## The thesis

Natural voice interaction is not produced by a model choice alone. It is a systems problem involving audio transport, partial recognition, endpointing, conversational timing, factual grounding, interruption recovery, speech synthesis, actions and measurement.

Aira explores a specific architecture we call **guarded speculative duplex orchestration**:

- listening, partial ASR, deterministic policy, semantic planning, playback and actions run as concurrent lanes;
- reasoning may begin from a stable partial transcript instead of waiting for a complete turn;
- speculative work is quarantined until the final transcript preserves its meaning;
- opt-out, consent, stale-response cancellation, action capability and claim safety are deterministic gates outside the LLM;
- an interruption becomes a conversational state—pause, clarification, new question or opt-out—not merely a cancelled audio buffer;
- the system exposes evidence, sources, actions and timings without exposing private hidden chain-of-thought.

This is **not one big model containing many submodels**. It is a modular asynchronous system whose components cooperate through typed events, cancellation tokens, generation IDs and causal gates.

## Is this a new voice-agent paradigm?

The broad pattern is not new enough to claim as a research invention. Streaming cascades, native duplex speech models and asynchronous augmentation already exist:

- [Moshi](https://arxiv.org/abs/2410.00037) models speech and text streams jointly for native full-duplex dialogue.
- [PersonaPlex](https://arxiv.org/abs/2602.06053) adds role and voice control to a full-duplex speech-to-speech model.
- [Kyutai Unmute](https://github.com/kyutai-labs/unmute) demonstrates a low-latency modular STT → text LLM → TTS stack.
- [MoshiRAG](https://kyutai.org/blog/2026-04-30-moshi-rag/) asynchronously augments a full-duplex speech model with retrieved knowledge.

The potentially publishable contribution is narrower: **can stable-partial speculation plus explicit safety and interruption-repair gates reduce perceived latency without increasing wrong starts, stale answers, grounding failures or unsafe actions?** That is a falsifiable systems question, not a branding claim.

The repository can support an open technical report or workshop paper after it contains controlled baselines, ablations, real-call audio, blind human ratings and confidence intervals. The proposed study and its honest novelty boundary are in [docs/RESEARCH_DIRECTION.md](docs/RESEARCH_DIRECTION.md).

## Running architecture

```text
Browser microphone — continuous 24 kHz audio
        │
        ▼
Duet session controller
        │
        ├── Sarvam Saaras v3
        │     streaming ASR, partial/final transcripts and speech events
        │
        ├── Turn assembler
        │     fragment merge, endpointing and stable-partial speculation
        │
        ├── Deterministic fast lane
        │     consent, opt-out, echo rejection, interruption repair,
        │     stale-response cancellation and capability/claim guards
        │
        ├── Gemini 3.1 Flash Lite
        │     grounded ASBL planning and objection handling
        │
        ├── ASBL action adapter
        │     idempotent brochure, callback, CRM and site-visit requests
        │
        └── Sarvam Bulbul v3
              persistent streaming TTS
                        │
                        ▼
                  Browser speaker
```

These lanes overlap, but causality cannot be parallelized away. The system needs enough stable caller intent before choosing an answer and enough verified response content before speaking it. The engineering objective is to move useful work before those gates and cancel invalid speculation cheaply.

The live implementation is described line by line in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What the demo does

Aira is a disclosed, permission-gated concierge for a person who has already expressed interest in ASBL Broadway. It can:

- explain verified project features and connect them to the caller's stated priorities;
- ask concise discovery questions without inferring hidden personality, wealth, emotion or protected traits;
- handle objections without fake scarcity, guaranteed returns or unsupported legal claims;
- accept barge-in and distinguish a pause request from a substantive question or opt-out;
- record idempotent brochure, callback, CRM and site-visit requests locally, or send the same allowlisted contract to an authenticated internal gateway;
- show a safe decision trace: transcript, intent, customer evidence, source IDs, action status and component timings.

Static demo facts live in [`agent/duet_agent/persona.py`](agent/duet_agent/persona.py). Prices, inventory, offers, payment schedules and unit-specific details are intentionally treated as volatile and require an authenticated source or advisor.

The ASBL name and project material are used for an internal engineering demonstration. This repository should not be presented as an official ASBL product or used for real outbound calling without organizational authorization, current source verification and applicable consent/telemarketing compliance.

## Run locally

Prerequisites: macOS on Apple Silicon, Python 3.12, [`uv`](https://docs.astral.sh/uv/), a Sarvam API key and a Gemini API key. The cloud-speech demo incurs provider usage; the local fallback is available but materially less natural.

```bash
git clone https://github.com/mssharatchandra/duet.git
cd duet
cp .env.example .env
# Add GEMINI_API_KEY and SARVAM_API_KEY to .env.

./scripts/setup-open-voice.sh
./scripts/run-live-demo.sh
```

Open <http://localhost:8990>, allow microphone access and use headphones for the cleanest barge-in test. The first run downloads model/runtime assets and therefore takes longer than later starts.

To exercise the complete WebSocket path with a synthetic caller while the server is running:

```bash
web-demo/.venv/bin/python scripts/smoke-live-demo.py
```

See [web-demo/README.md](web-demo/README.md) for local ASR/TTS fallbacks, tuning flags and the secondary Hermes learning-agent mode.

## What is measured today

| Surface | Implemented | Current evidence | Missing before a strong claim |
|---|---|---|---|
| Unit and flow correctness | Yes | 149 passing tests across turn assembly, policy, actions, ASR/TTS adapters and interaction flow | Public multi-user and telephony integration tests |
| LLM behavior | Yes | 17-scenario live Gemini golden set with a 90% CI gate | Larger adversarial and multilingual sets |
| ASR | Yes | WER-by-noise/reverb/speed matrix; Parakeet MLX leads the tested local candidates | Consent-cleared real microphone and phone audio |
| TTS | Partial | TTFB/RTF harness for local voices; live Sarvam timings in smoke tests | Blind MOS, intelligibility and prosody ratings |
| Duplex interaction | Partial | Synthetic interruption/cancellation smoke and Takeover Rate harness | Human overlap, false-barge and interruption-repair study |
| Naturalness | Not yet established | First human trial was treated as a failed naturalness eval and drove corrective work | Blind paired comparison with confidence intervals |
| Cost | Partial | Token/GPU cost schema and benchmark roll-up | Actual per-minute provider and telephony bill from repeated calls |

The old benchmark outputs under `eval/bench/out/` are development artifacts, not the headline evidence for the current Aira architecture. Reproducible commands and the evaluation contract are in [eval/README.md](eval/README.md).

## Observability: implemented versus wired

The repository contains a self-hosted observability stack:

- **Langfuse:** traces benchmark reasoning calls, model latency, token usage and estimated API cost.
- **Postgres + Grafana:** stores per-call latency, takeover, overlap and cost records and provisions a Duet dashboard.
- **Prometheus:** infrastructure collection is configured.
- **Loki:** container is staged for log aggregation.
- **GitHub Actions:** lints, runs tests on Linux and Apple Silicon, gates live Gemini behavior at 90%, and boots the observability stack to verify Langfuse ingestion, Grafana provisioning and Postgres writes.

This is not yet complete live-demo observability. The browser session does not currently create a Langfuse trace per conversation, expose application `/metrics`, or ship structured session logs to Loki. Those three integrations are P0 before calling the service production-observable.

Run the existing stack locally:

```bash
cd infra
cp .env.example .env
# Rotate every development credential in .env before shared use.
docker compose -p langfuse -f langfuse-compose.yml up -d
docker compose -p duet-obs -f observability-compose.yml up -d
```

Langfuse: <http://localhost:3000> · Grafana: <http://localhost:3001> · Prometheus: <http://localhost:9099>. See [infra/README.md](infra/README.md).

## Free calling POC versus real PSTN

There is no genuinely free public telephone network: phone numbers and carrier termination cost money. There are, however, two no-carrier-cost ways to prove the media adapter:

1. **Browser/WebRTC:** keep the current browser demo or place it behind self-hosted LiveKit OSS.
2. **SIP lab:** run [Asterisk](https://www.asterisk.org/products/software/) on the VPS and call between two SIP softphones. Asterisk is GPLv2 software, and its current [WebSocket channel driver](https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/) supports bidirectional media suitable for an adapter POC.

For one real-phone demonstration, a provider trial is the practical bridge. [Twilio's current free trial](https://www.twilio.com/docs/usage/trials) advertises limited trial voice usage but restricts recipients and geography; India availability must be verified in the account. Exotel remains the better India-oriented production candidate, but it is paid. Browser, SIP and PSTN adapters should all feed the same Duet session contract so the conversational brain is not forked per transport.

## Research programme

The central experiment compares:

1. sequential streaming cascade;
2. concurrent lanes without transcript speculation;
3. stable-partial speculation without semantic confirmation;
4. speculation with final-transcript semantic confirmation;
5. confirmation plus interruption-repair state machine;
6. the complete system with grounding and capability gates.

Primary metrics are p50/p95 end-of-speech-to-first-audio, wrong-start and cancellation rate, interruption yield, inappropriate overlap, task completion, factual/policy violations, naturalness, intelligibility and cost per minute. A latency win that damages task success or trust is a failed result.

## Repository map

| Path | Purpose |
|---|---|
| [`agent/`](agent/) | Turn-taking, persona, reasoning, actions, ASR/TTS adapters and telemetry |
| [`web-demo/`](web-demo/) | Browser microphone/speaker runtime and inspectable session UI |
| [`eval/`](eval/) | Reasoning, ASR, TTS, duplex and blind-human evaluation harnesses |
| [`infra/`](infra/) | Langfuse, Postgres, Grafana, Prometheus and Loki Compose stack |
| [`docs/`](docs/) | Architecture, decisions, research plan, product specification and learning material |
| [`.github/workflows/`](.github/workflows/) | CI correctness, live behavior gate and observability-stack smoke tests |

## Production boundary

The localhost demo is single-session and unauthenticated. Public or outbound deployment requires, at minimum: one isolated session per call, TLS/WSS, authentication, durable consent and do-not-contact state, retention/deletion controls, rate and duration limits, current fact tools, human transfer, provider failure fallbacks, live traces/metrics/logs and load testing. See [docs/ASBL_VOICE_AGENT.md](docs/ASBL_VOICE_AGENT.md) for the full boundary.

## Contributing and license

The project is licensed under [Apache 2.0](LICENSE). Useful contributions include real-audio eval fixtures with explicit rights, transport adapters, interruption scenarios, provider-independent contracts and reproducible ablations. Do not contribute customer recordings, personal data, private ASBL systems or proprietary project information.
