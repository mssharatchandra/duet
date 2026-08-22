# Duet / Aira architecture

This document describes the code that runs today and clearly separates it from the deployment
target. Aira is currently a controlled-duplex, interruptible cascade—not a native end-to-end
speech-to-speech model.

## Running system

```text
Browser microphone (24 kHz float PCM)
        │  WebSocket; mic remains live while Aira speaks
        ▼
web-demo/server.py ───────── session state / consent / opt-out / generation IDs
        │
        ├──► Sarvam Saaras v3 realtime WebSocket
        │       └── interim transcripts + speech-start/end events
        │
        ├──► TurnAssembler
        │       └── merges provider fragments; stable-partial speculation; final-turn gate
        │
        ├──► deterministic policy lane
        │       ├── permission and do-not-contact
        │       ├── pause / vague-interruption clarification
        │       ├── echo-aware barge-in and stale-response cancellation
        │       └── capability, repetition and sensitive-trait guards
        │
        ├──► Gemini 3.1 Flash Lite API (asynchronous semantic planner)
        │       ├── bounded conversation history
        │       ├── ASBL fact registry and objection playbook
        │       └── streamed talking point + final structured audit metadata
        │
        ├──► ActionLayer (asynchronous)
        │       └── local idempotent ledger today; allowlisted internal HTTPS gateway when configured
        │
        └──► Sarvam Bulbul v3 persistent WebSocket
                └── 24 kHz PCM → clock-paced server queue → adaptive browser jitter buffer
                                                        │
                                                        ▼
                                                   loudspeaker
```

These lanes overlap, but two causal gates remain: enough stable caller intent must exist before an
answer can be chosen, and enough verified response content must exist before audio can be spoken.
The UI exposes intent, evidence, fact sources, actions and timings; it intentionally does not expose
private hidden chain-of-thought.

## Barge-in state machine

1. Provider speech-start yields the acoustic floor and clears server and browser playback.
2. The interim transcript rejects backchannels and likely loudspeaker echo.
3. The final transcript determines what the interruption meant:
   - `stop` / opt-out: end and latch do-not-contact;
   - `wait` / `hold on`: acknowledge briefly and wait;
   - vague change such as `actually, no`: ask whether to stop or clarify;
   - complete question or objection: supersede stale reasoning and answer normally.
4. Cancelled Sarvam TTS sockets are discarded so unread audio cannot leak into the next turn.

## Source of truth

- Static verified project facts and source IDs: `agent/duet_agent/persona.py`.
- Volatile price, inventory, offers, legal interpretation and unit-specific details must come from
  an authenticated ASBL tool or human advisor.
- Conversation memory currently lives in one process for one session. The action ledger is local
  unless `ASBL_ACTION_MODE=remote` is configured.
- The repo-root `.env` contains provider credentials locally and is gitignored.

## Current limitations

- Only one browser session can be active at a time.
- The web server is not yet containerized or authenticated for public use.
- There is no telephony media adapter, call-origination service, durable consent ledger or human
  transfer path yet.
- Browser echo cancellation is useful but not a production acoustic correctness boundary.
- Gemini and Sarvam are hosted dependencies; the repository does not contain their model weights.

## VPS deployment target

The present cloud-speech architecture is suitable for a CPU VPS because the VPS orchestrates audio
and state while Gemini and Sarvam perform inference. The production topology should be:

```text
Internet / phone network
        │
        ▼
Caddy :443 ── TLS + WSS ── Aira API/media service (one isolated Session per call)
                                  ├── Postgres: consent, DNC, call/action audit, lead state
                                  ├── provider adapters: Sarvam + Gemini
                                  ├── ASBL internal action gateway
                                  └── Prometheus/Loki/Langfuse telemetry
```

Before exposing it, replace the process-global single session, add signed session tokens and origin
checks, enforce server-side call duration/rate limits, add readiness/liveness probes, persist consent
and DNC before dialing, and package the service behind Caddy in Docker Compose.

## Telephone adapter

For India, Exotel AgentStream is the natural first integration candidate: its Voicebot applet sends
caller audio to a secure WebSocket and accepts bot audio back. Twilio Media Streams and Plivo Audio
Streams provide equivalent bidirectional transports. The adapter is deliberately thin:

```text
telephony 8/16 kHz frames ⇄ codec/resampler ⇄ existing Session queues ⇄ Sarvam / Gemini / TTS
          call events     ⇄ consent + call state              playback clear on barge-in
```

Telephony must not fork the conversation brain. Browser and phone calls should share the same turn,
policy, reasoning, action and evaluation code. Only media framing, codec conversion, authentication,
call control and provider-specific clear/mark events belong in the adapter.

Real outbound use is gated on ASBL approval and TCCCPR/DLT-compliant consent and preferences. A safe
technical demo should initially call only an explicitly allowlisted team number.

