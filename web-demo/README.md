# Duet browser demo

When `SARVAM_API_KEY` is configured, the default browser path is:

```text
browser mic -> Sarvam realtime VAD + true Saaras interim/final ASR
            -> stable-partial speculation -> guarded streamed Aira/Gemini speech
            -> persistent Sarvam Bulbul WebSocket TTS -> browser speaker
```

Without a Sarvam key it falls back to the fully local Silero VAD -> Parakeet
MLX -> Hermes -> Piper path. The default remains guarded half-duplex. The live
presentation launcher enables **controlled barge-in**: browser echo cancellation
keeps the Sarvam stream live while Duet speaks, and provider speech-start cancels
TTS on the provider, server and browser. The final transcript then resolves whether
the interruption was a clear question, a change requiring clarification, or opt-out. This is an interruptible
cascade, not a native speech-to-speech duplex model. Headphones are recommended.

For the live SDR demo:

```bash
./scripts/run-live-demo.sh
```

Then open <http://localhost:8990>. A repeatable synthetic-caller check is also
available while the server is running (it makes small real Sarvam/Gemini calls):

```bash
web-demo/.venv/bin/python scripts/smoke-live-demo.py
```

Set up the isolated voice runtime once:

```bash
./scripts/setup-open-voice.sh
```

The separate `web-demo/.venv` is intentional. Moshi 0.3 pins an old
`huggingface-hub`, while current Parakeet MLX requires a new one; forcing both
into one environment produces an unsatisfiable dependency graph.

## Hermes Voice v0

From the Duet repository root, with `hermes-brain` checked out beside it:

```bash
web-demo/.venv/bin/python web-demo/server.py --mode hermes
```

Open <http://localhost:8990>, press **Start talking**, answer each due recall
question, and self-grade it. With Sarvam enabled, microphone audio is sent to
Sarvam for transcription and tutor text is sent to Sarvam for speech. Hermes'
source article is not sent to Sarvam, and it is not sent to Gemini unless you
explicitly enable remote grading. At the end, the score is written only after
you press **Record this review in Hermes**. The server delegates that write to
`hermes-brain/scripts/brain.py review` and verifies the new event before
reporting success.

Useful options:

```bash
# Keep all ASR and TTS processing on this Mac
web-demo/.venv/bin/python web-demo/server.py --mode hermes \
  --asr parakeet --tts-backend piper

# Sarvam recognition modes: transcribe, verbatim, or codemix
web-demo/.venv/bin/python web-demo/server.py --mode hermes \
  --sarvam-mode codemix --sarvam-language en-IN

# Wait a little longer across thinking pauses before committing a turn
web-demo/.venv/bin/python web-demo/server.py --mode hermes --turn-grace-ms 650

# Practice a particular approved run, even if it is not due
web-demo/.venv/bin/python web-demo/server.py --mode hermes \
  --hermes-run oauth-2-1-pkce-for-remote-mcp-agents

# Exercise the UI and loader without spoken output
web-demo/.venv/bin/python web-demo/server.py --mode hermes --voice-stack none

# Explicit privacy trade-off: send the reviewed article and answers to Gemini
# for automatic grading. The page displays this disclosure during the session.
web-demo/.venv/bin/python web-demo/server.py --mode hermes --hermes-remote-grading
```

Set `HERMES_BRAIN_PATH` or pass `--hermes-root` when the repositories are not
siblings. Only Hermes runs whose manifest status is `approved` or `published`
can be loaded.

The page shows live recognition state, the turn-continuation grace period,
recognition time, and playback pause state. Local mode also shows room
calibration, input RMS, the adaptive energy threshold, Silero rejection, and
verified speech duration. Useful overrides:

```bash
# Compatibility fallback; Silero still validates speech before Whisper
web-demo/.venv/bin/python web-demo/server.py --asr whisper:small.en

# Experimental higher-quality voice; currently crashes during process teardown
# on this Mac, so it is not the default.
web-demo/.venv/bin/python web-demo/server.py --tts-backend kokoro

# Retain the original experimental full-duplex model (agent environment)
agent/.venv/bin/python web-demo/server.py --voice-stack moshi
```

These threshold controls apply only to the local ASR path. If quiet speech
never reaches Silero, lower `--asr-min-rms` from `0.003`.
If non-speech passes Silero, raise `--vad-threshold` from `0.55`. Do not lower
either value merely to force a transcript; rejected noise is correct behavior.

## ASBL Broadway outbound-concierge demo

The default mode is Aira, a disclosed and permission-gated ASBL Broadway AI
concierge for a consented enquiry callback:

```bash
./scripts/run-live-demo.sh
```

The page exposes deterministic policy decisions, evidence-backed readiness
signals, source links, response strategy, capability checks, and speech latency.
The runtime row shows concurrent lanes rather than a numbered waterfall. Local
brochure/callback/site-visit requests are genuinely written to `.local/asbl-actions.jsonl` as
accepted requests; configure `ASBL_ACTION_GATEWAY_URL` to send the same idempotent contract to the
internal ASBL product. Aira never promotes `accepted` to `completed` without the adapter response.
It deliberately does not expose private chain-of-thought. Readiness is not presented as purchase
probability. This server is still single-user and localhost-only; real outbound
activation requires persistent consent/DNC, compliant telephony, CRM and human
handoff as defined in `docs/ASBL_VOICE_AGENT.md`.
