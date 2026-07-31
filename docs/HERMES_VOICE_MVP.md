# Hermes Voice — the leapfrog MVP (proposed 2026-07-07)

**One line:** give hermes-brain a full-duplex voice — spoken recall drills and Socratic challenge
over the spaced-repetition schedule it already computes, running on hardware you already own, for
~$1/month instead of ~$90.

## Why this instead of a generic "Jarvis"

A generic personal assistant competes with Siri, Alexa, Gemini Live and ChatGPT Voice — all
better-funded, and all solving *your* problem worse than they solve the average person's. This
instead exploits three things nobody else has:

1. **hermes-brain already has the content and the schedule.** `config/brain.json` defines
   `review_intervals_days: [1, 3, 7, 14, 30, 90]`; every `learning/<run>/` ships a `recall.md`.
   Today those prompts are read. There is no reason they can't be *spoken*.
2. **Duet is full-duplex.** No flashcard app, tutor, or voice assistant on the market can be
   interrupted mid-sentence or backchannel while you think. For *recall practice specifically*
   that's not a gimmick: the tutor can cut in the moment you go wrong, and stay quiet while you
   struggle for the answer — which is exactly when learning happens.
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
| Reasoning brain (Gemini Flash-Lite, measured $0.00035/call) | ~$0.60 |
| Tunnel (Cloudflare Tunnel / Tailscale free tier) | $0 |
| **Total** | **≈ $1** |

**That's ~98% cheaper, not 70%** — but only because of one non-obvious decision, which is the
whole engineering lesson here:

> **For a personal agent, the enemy is idle time, not per-minute inference.** An always-on cloud
> GPU at $0.40/hr costs **$292/month** — *worse than ElevenLabs* — because you talk to it 20
> minutes a day and pay for 1,440. Scale-to-zero serverless fixes the bill but adds a 10–30 s cold
> start that destroys the "instant" feel. Local-first on hardware you own beats both on cost *and*
> latency, and wins privacy outright: your notes, calendar and half-formed thoughts never leave
> the machine.

Honest costs of that choice: the Mac must be awake and reachable; Moshi's voice is worse than
ElevenLabs'; no phone number until we add telephony.

## MVP scope — buildable today

Everything below reuses Duet's existing loop, injector, brain, web UI and telemetry. No new
architecture.

1. **Due-card loader** — read `learning/*/recall.md` + `review_intervals_days`, plus a review log
   (JSONL, written back to hermes-brain following its own schema conventions), and pick what's due.
2. **Tutor persona** — swap `persona.py`'s SDR fact-sheet for the due card's content: ask the
   question, wait, grade, follow up Socratically on weak answers. Same `Guidance` contract.
3. **Spoken grading → written state** — the async brain scores your spoken answer against the
   card's expected answer and appends a review record so the next interval schedules correctly.
   Deterministic scheduling stays in Python (same split as the BANT rubric: judgment in the model,
   arithmetic in code).
4. **Reachable from your phone** — Cloudflare Tunnel over the existing web demo. Drill while walking.
5. **Live cost meter** — the page shows $ spent this session next to "what ElevenLabs would have
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

**PROPOSED — awaiting go.** Phase 1 is ~a day of work, $0 additional spend. hermes-brain is a
separate private repo with its own `CLAUDE.md`/`AGENTS.md` conventions and schema gates; any
writes there must follow its rules, so the loader/review-log design needs a read of those first.
