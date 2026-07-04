# Duet

**A full-duplex naturalness layer for voice AI.**

Most production voice agents — including well-funded, revenue-generating ones — still run a *cascaded* pipeline: speech-to-text → LLM → text-to-speech, glued together with "wait for silence, then respond" turn-taking. It works, but it feels like talking to a walkie-talkie. Duet is an open-source conversational layer that gives an existing cascaded voice-AI stack genuine full-duplex behavior: the agent listens *while* it speaks, backchannels ("mm-hm", "right"), recovers from mid-sentence interruptions, and responds in under ~300ms — without the platform rebuilding its stack.

**Status: Phase 0 — scaffolding.** Nothing below this line is a claim yet. Every claim that appears here later (latency, naturalness delta, cost per minute) will link to a reproducible benchmark in [`/eval`](eval/), or it won't appear at all.

## Who this is for

Teams running cascaded voice-AI pipelines in production (outbound sales, lead qualification, support) who want the conversational feel of native full-duplex models without betting the stack on one. Not end consumers.

## Planned architecture (subject to the decisions log)

- **Duplex core:** a native full-duplex speech model owns real-time conversational flow — timing, backchannels, interruption recovery. See [DECISIONS.md](docs/DECISIONS.md) for the CSM vs. Moshi analysis.
- **Async reasoning layer:** anything requiring actual intelligence (lead qualification, objection handling) is delegated to a fast frontier model asynchronously, injected into the conversation without blocking the audio loop.
- **Honest benchmark:** the same SDR persona runs on Duet and on a fully open-source cascaded baseline (faster-whisper + Piper), measured on latency and turn-taking cleanliness, with blind human naturalness ratings. If the delta is small, that gets published too.

## Repo map

| Path | What lives here |
|---|---|
| [`/agent`](agent/) | The duplex core + async reasoning layer |
| [`/eval`](eval/) | Benchmark harness, Takeover Rate metric, cascaded baseline |
| [`/infra`](infra/) | Docker Compose stack: LiveKit OSS, Langfuse, Prometheus, Grafana, Postgres, Caddy |
| [`/web-demo`](web-demo/) | Public demo: landing page, email gate, session-capped live calls |
| [`/docs`](docs/) | [DECISIONS.md](docs/DECISIONS.md) (engineering journal) · [LEARNING.md](docs/LEARNING.md) (voice-AI curriculum) |

## License

[Apache 2.0](LICENSE).
