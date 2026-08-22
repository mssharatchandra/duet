# Hermes Voice — the leapfrog MVP (v0 built 2026-08-01)

**One line:** give hermes-brain a reliable local voice — spoken recall drills and Socratic challenge
over the spaced-repetition schedule it already computes, running on hardware you already own, for
~$1/month instead of ~$90.

## Why this instead of a generic "Jarvis"

A generic personal assistant competes with Siri, Alexa, Gemini Live and ChatGPT Voice — all
better-funded, and all solving *your* problem worse than they solve the average person's. This
instead exploits three things nobody else has:

1. **hermes-brain already has the content and the schedule.** `config/brain.json` defines
   `review_intervals_days: [1, 3, 7, 14, 30, 90]`; every `learning/<run>/` ships a `recall.md`.
   Today those prompts are read. There is no reason they can't be *spoken*.
2. **Duet is a voice-AI laboratory, not a wrapper around one vendor.** The first full-duplex
   attempt failed human evaluation by hearing its own output and inventing user speech. The reliable
   v0.1 is half-duplex; interruption and backchannels return only when measured acoustic ownership
   makes them safe.
3. **hermes-brain's own thesis invites it.** "Models and harnesses are replaceable executors.
   Markdown, JSON/JSONL, Git, and the schemas in this repository are the durable interface."
   A voice agent is simply one more harness. Nothing about the brain changes.

Bonus loop worth naming: you learn applied voice AI *by building the tool that drills you on
what you're learning*. The artifact and the curriculum are the same object.

## The cost argument (real numbers)

Commercial per-minute rates, 2026 (see sources in the chat thread / README):
ElevenLabs Conversational $0.08–0.10 · Vapi $0.07–0.25 realistic · Retell $0.13–0.31 realistic ·
Bolna ~$0.06 + telephony. Industry range: **$0.05–0.35/min**.

At 20 minutes/day (600 min/month) that's **$48–90/month**, and up to $200 at the high end.

Hermes Voice, local-first:

| Component | Cost/month |
|---|---|
| GPU (Apple M5 you already own) | **$0** — measured 48 ms/step, well inside the 80 ms budget |
| Electricity (~15 h at ~40 W) | ~$0.10 |
| Reasoning brain | $0 with self-grading; optional Gemini grading has not yet been costed on this tutor |
| Tunnel (Cloudflare Tunnel / Tailscale free tier) | $0 |
| **Total** | **≈ $1** |

**That's ~98% cheaper, not 70%** — but only because of one non-obvious decision, which is the
whole engineering lesson here:

> **For a personal agent, the enemy is idle time, not per-minute inference.** An always-on cloud
> GPU at $0.40/hr costs **$292/month** — *worse than ElevenLabs* — because you talk to it 20
> minutes a day and pay for 1,440. Scale-to-zero serverless fixes the bill but adds a 10–30 s cold
> start that destroys the "instant" feel. Local-first on hardware you own beats both on cost *and*
> latency. Privacy depends on grading mode: self-grading stays local; explicit Gemini grading sends
> the reviewed article and spoken answer to Google and the UI says so.

Honest costs of that choice: the Mac must be awake and reachable; Piper's voice is less expressive
than premium hosted TTS; v0.1 cannot be interrupted while speaking; no phone number until telephony.

## MVP scope

Everything below reuses Duet's Hermes adapter, brain, web UI and telemetry. The live voice boundary
is now a guarded local cascade rather than Moshi's unguarded microphone loop.

1. ✅ **Due-card loader** — read `learning/*/recall.md` + the review event log
   (JSONL, written back to hermes-brain following its own schema conventions), and pick what's due.
2. ✅ **Tutor session** — ask the approved run's numbered questions, reject overlapping answers,
   support repeat/skip, and keep strict integer scoring deterministic.
3. ✅ **Spoken review → written state, human-gated** — local self-grading is the default; optional
   Gemini grading is explicit. The final button calls Hermes' canonical `brain.py review` command
   and reads back the appended event. Partial answers count as incorrect in Hermes' integer score.
4. ⬜ **Reachable from your phone** — Cloudflare Tunnel over the existing web demo. Drill while walking.
5. ⬜ **Live cost meter** — the page shows $ spent this session next to "what ElevenLabs would have
   billed." Teaching instrument and build-in-public asset in one.

**Explicitly out of scope for v1:** telephony, wake word, multi-user, voice cloning, cloud hosting.

## Build-in-public phases (each = one shippable artifact + one measured result)

| Phase | Build | Post | Measured claim |
|---|---|---|---|
| 1 | Hermes Voice v0 (above) | "I gave my second brain a voice you can interrupt" | $/session vs commercial |
| 2 | MCP tools in the brain | "Voice + MCP: an assistant that *does* things" | tool-call latency, fully masked? |
| 3 | Semantic turn detection | "Fixing the rudest thing about my voice agent" | takeover 0.24 → <0.10 |
| 4 | Voice-quality tier (Chatterbox) | "Prettier voice, worse conversation" | naturalness vs handoff tradeoff |
| 5 | Speech-native LLM (Ultravox/Qwen3-Omni) | "What ASR throws away" | paralinguistic eval |
| 6 | Telephony | "It has a phone number now" | survives a real call |
| 7 | Cost teardown | "$1/month vs $90/month, itemized" | full TCO |

Phases 3–6 are the [BUILD_WORLDCLASS](BUILD_WORLDCLASS.md) projects — the roadmap and the product
are the same path.

## Status

**V0 BUILT LOCALLY, NOT YET HUMAN-EVALUATED.** The loader, tutor state machine, browser UI,
privacy split, confirmed Hermes review write, local ASR/TTS adapters, and hallucination filters are
implemented and covered by 89 unit tests. The guarded WebSocket path spoke the real due OAuth
question, paused ASR throughout playback, then transcribed the captured real “Hello” exactly and
delivered it to the tutor. A complete fresh spoken review with a human learner still needs to run
before experience claims.
