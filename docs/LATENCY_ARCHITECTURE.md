# Duet latency architecture

## What is parallel and what is causal

The browser used to draw five numbered boxes. That was a misleading waterfall. Duet is a set of
concurrent runtime lanes with two deliberate semantic gates:

```text
microphone ── streaming ASR ── partial transcript ── provisional intent / fact prefetch
                         │
                         └── stable-turn gate ── response stream ── verified-clause gate ── TTS stream
                                  ├── deterministic consent / opt-out / claim guards
                                  ├── retrieval and conversation memory
                                  └── async action requests and audit events

speaker   ────────────────────────────────────────────────────────────────► audio
microphone / ASR remain armed during playback for controlled barge-in ───► interruption
```

Listening, partial transcription, acoustic interruption detection, deterministic policy, retrieval,
memory work, playback, observability and tool execution can overlap. Two things cannot honestly be
made fully parallel: Duet needs enough stable user intent before choosing an answer, and it needs
enough verified answer content before speaking it. Native speech-to-speech models hide more of this
pipeline inside one model, but they do not repeal those information dependencies.

## Measured current state — 2026-08-23

`scripts/smoke-live-demo.py` measures from Sarvam's final speech-end event to the first TTS audio
chunk received by the local web server. Three real-service runs of the same grounded ASBL discovery
turn produced:

| Run | Turn assembly | Commit → brain result | TTS first audio | Total |
|---:|---:|---:|---:|---:|
| 1 | 623 ms | 1,649 ms | 443 ms | 2,715 ms |
| 2 | 611 ms | 1,739 ms | 341 ms | 2,691 ms |
| 3 | 650 ms | 1,769 ms | 479 ms | 2,898 ms |
| **Median** | **623 ms** | **1,739 ms** | **443 ms** | **2,715 ms** |

This tiny synthetic sample is a regression probe, not a production latency study. It excludes public
internet WebRTC/telephony jitter and browser playout buffering. It nevertheless answers the key
question: the current rich response path is too slow. Gemini's one-shot structured response is the
largest component, and current TTS waits for that complete JSON response before beginning.

### Corrective runtime measurement later the same day

The original table remains above as the before-measurement. The runtime now uses realtime STT
interims, speculative-but-gated reasoning, Gemini response streaming and a pre-warmed persistent TTS
WebSocket. Two real-service probes measured **1,622 ms** and **2,614 ms** from provider speech-end to
first server TTS audio. In the faster run, stable-partial speculation hid roughly 600 ms of Gemini;
in the slower run it did not. Warm TTS alone measured **223 ms**, and speech-start to playback cancel
measured **349 ms** through the browser protocol. Add roughly 160 ms for the browser's two-frame
jitter buffer when comparing with audible latency.

This remains above the 650–900 ms goal and materially above 300–400 ms. The latter is not a credible
rich-response target on this exact stack: 220 ms endpointing plus 223–470 ms TTS consumes the budget
before semantic reasoning or browser playout. A 300–400 ms *acknowledgment* is possible through a
deterministic fast lane; that is not the same claim as a grounded answer.

## Market context — compare definitions before numbers

Vendor figures use different clocks, regions, models and transports. They are useful targets, not an
independent benchmark:

| System | Published figure | Important qualification |
|---|---:|---|
| Retell | as low as 600 ms | Official estimate from user stop to response; configuration dependent |
| Vapi | under 500 ms average on its homepage; FAQ says about 800 ms end to end | Vapi explicitly documents endpointing, STT, model and TTS as causal contributors |
| Deepgram Voice Agent | 640 ms and 850 ms examples | Their latency reports expose EOT, LLM TTFT and TTS TTFT separately |
| Bolna | homepage under 300 ms; platform docs under 600 ms | Vendor claim; engine docs recommend 200–300 ms endpointing and 400–500 ms linear delay |
| ElevenLabs | Flash model inference around 75 ms; South Asia Flash WebSocket TTFB around 150–200 ms | TTS component latency, not complete conversational latency |
| Duet now | **2,715 ms median, n=3** | End-of-speech through turn assembly, Gemini result and Sarvam first audio on the current demo |

Sources: [Retell latency](https://docs.retellai.com/reliability/check-estimated-latency),
[Vapi latency model](https://docs.vapi.ai/assistants/model-intelligence/understanding-latency),
[Vapi FAQ](https://docs.vapi.ai/faq),
[Deepgram latency report](https://developers.deepgram.com/docs/voice-agent-latency-report),
[Bolna platform concepts](https://www.bolna.ai/docs/platform-concepts),
[Bolna engine tuning](https://www.bolna.ai/docs/agent-setup/engine-tab), and
[ElevenLabs latency](https://elevenlabs.io/docs/developer-guides/reducing-latency).

## The next implementation target

The goal is **650–900 ms median and below 1.2 seconds p95** for a grounded response, while keeping
interruption and factual safety. The work should be measured after each change:

1. Replace the fixed continuation delay with confidence-aware endpointing: provisional at 200–350 ms,
   extended only for unfinished syntax, fillers or a likely continuation.
2. Start retrieval, intent classification and deterministic policy on stable partial transcripts;
   cancel speculative work when the transcript changes.
3. Split the response contract. Stream speakable clauses immediately; emit fact IDs, lead evidence,
   actions and audit metadata on a parallel structured channel instead of waiting for one JSON object.
4. Keep a 4–10 word safe clause buffer, then stream it to a persistent Sarvam TTS WebSocket while
   the model generates the next clause. Cancel both streams on barge-in.
5. Add a deterministic fast path for greetings, consent, opt-out, acknowledgments and action receipt.
6. Report p50/p95 end-of-speech→first-audible-sample, false endpoints, interruption yield time,
   word-error rate and factual-policy failures together. Latency alone is not naturalness.

The product claim today is therefore precise: Duet is a working, inspectable, controlled-duplex ASBL
agent with real interruption, stable-partial speculation, guarded streamed speech and grounded
decisions. Its rich-response latency is improved but is not yet competitive with the best commercial
voice-agent paths.
