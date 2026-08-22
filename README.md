# Duet

**An interruptible, consent-first voice interaction layer—currently proven through Aira, an ASBL Broadway property concierge.**

Most voice agents still run a cascaded pipeline: speech-to-text → LLM → text-to-speech. Duet explores the interaction engineering that determines whether that pipeline feels humane: turn assembly, interruption, playback cancellation, policy, memory and evaluation. The current demo uses Sarvam streaming speech and Gemini reasoning with Duet-owned controlled barge-in. It is an interruptible cascade, not yet a native full-duplex model.

**Status: Aira for ASBL Broadway is running locally.** It discloses that it is an AI, asks permission before discovery, answers from a versioned fact registry, yields to spoken interruptions, and fails closed on opt-out and forbidden real-estate claims. The real-service path passes an end-to-end synthetic caller test and the current suite has 131 unit/flow tests. Its measured rich-turn median is currently 2.715 seconds (three runs), so it is not yet latency-competitive; see the [latency architecture and market comparison](docs/LATENCY_ARCHITECTURE.md). It still needs real-caller, multilingual, telephony and blind-naturalness evaluation before any “production ready” or “world-class” claim.

## Try the ASBL Broadway demo

```bash
./scripts/run-live-demo.sh
```

Open <http://localhost:8990>, allow the microphone, grant Aira permission, and interrupt it during an answer. The [ASBL product and architecture spec](docs/ASBL_VOICE_AGENT.md) defines the production boundary, memory policy, evals and talk narrative.

## Try Hermes Voice (secondary learning-agent mode)

With `hermes-brain` checked out beside this repository:

```bash
./scripts/setup-open-voice.sh
web-demo/.venv/bin/python web-demo/server.py --mode hermes
```

Open <http://localhost:8990>. Grading and Hermes source material stay local by
default. When Sarvam is configured, spoken audio and tutor speech are processed
by Sarvam; the [browser-demo guide](web-demo/README.md) documents the fully
local mode, explicit remote grading, run selection, and no-model smoke path.

## Who this is for

Teams running cascaded voice-AI pipelines in production (outbound sales, lead qualification, support) who want the conversational feel of native full-duplex models without betting the stack on one. Not end consumers.

## Architecture direction (subject to the decisions log)

- **Provider-independent interaction layer:** hosted or local speech engines sit below Duet-owned turn assembly, playback ownership, memory, and evaluation.
- **Reliable local fallback:** neural VAD, Apple-native ASR, reasoning, and local TTS remain available with the same interaction contract.
- **Duplex experiment:** a native speech model explores timing, backchannels, and interruption recovery, but does not become the default until it beats the guarded cascade in human evaluation.
- **Concurrent interaction lanes:** listening, partial ASR, guards, playback and actions overlap; stable-intent and verified-clause gates preserve conversational and factual correctness.
- **Capability-backed actions:** local requests are auditable in an ignored JSONL ledger; the same idempotent contract can call ASBL's internal product, and completion is claimed only after its acknowledgement.
- **Honest benchmark:** the same SDR persona runs on Duet and on a fully open-source cascaded baseline (faster-whisper + Piper), measured on latency and turn-taking cleanliness, with blind human naturalness ratings. If the delta is small, that gets published too.

## Repo map

| Path | What lives here |
|---|---|
| [`/agent`](agent/) | The duplex core + async reasoning layer |
| [`/eval`](eval/) | Benchmark harness, Takeover Rate metric, cascaded baseline |
| [`/infra`](infra/) | Docker Compose stack: LiveKit OSS, Langfuse, Prometheus, Grafana, Postgres, Caddy |
| [`/web-demo`](web-demo/) | Aira property-concierge demo and Hermes spoken-recall mode |
| [`/docs`](docs/) | [Architecture](docs/ARCHITECTURE.md) · [The 80/20 voice-AI blog](docs/blog/voice-ai-the-80-20.md) · [DECISIONS.md](docs/DECISIONS.md) (journal) · [LEARNING.md](docs/LEARNING.md) (curriculum) |

## License

[Apache 2.0](LICENSE).
