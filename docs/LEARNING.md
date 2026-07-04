# LEARNING.md — the voice-AI curriculum

This project doubles as a noob→expert course in real-time speech AI. Each phase of the build
unlocks a lesson; each lesson is written *after* building, so it explains real code in this repo,
not textbook abstractions. Checkboxes = what you should be able to explain to someone else.

---

## Lesson 0 (Phase 0) — Why voice bots feel robotic: the anatomy of a cascaded pipeline

**The stack everyone runs today:** `mic → VAD → ASR → LLM → TTS → speaker`, as a loop of
strict turns. Each stage is fine; the *composition* is what kills naturalness.

**Where the latency actually comes from** (rough production numbers):

| Stage | What it does | Typical cost |
|---|---|---|
| VAD endpointing | Waits for silence to decide you're "done" | **500-800ms** — the single biggest offender, and it's a *deliberate wait*, not compute |
| ASR finalization | Streaming ASR revises its hypothesis until endpoint | 100-300ms after endpoint |
| LLM time-to-first-token | The brain starts answering | 200-800ms |
| TTS time-to-first-byte | First audio comes out | 100-300ms |

Total: **1-2.5s of dead air** after you stop talking. Humans respond in ~200ms — and frequently
*overlap*. That gap is the entire product opportunity.

**Vocabulary you now own:**
- **Half-duplex vs full-duplex:** walkie-talkie vs telephone. Cascades are architecturally half-duplex — while the bot speaks, its ears are off (or naively open, causing echo/self-interruption problems).
- **Barge-in:** user interrupts the bot mid-utterance. Cascades handle it by *killing TTS playback and throwing away state* — the bot doesn't know how much of its sentence you actually heard.
- **Backchannel:** "mm-hm", "right", "oh wow" — signals of listening that occur *during* the other speaker's turn. Impossible by construction in a turn-based pipeline.
- **Endpointing:** deciding the user finished. Silence-based endpointing is why bots interrupt you when you pause to think, yet feel sluggish when you finish cleanly. Smarter variants ("semantic VAD") predict completion from *content*, not silence.
- **Takeover Rate:** how often the agent grabs the turn inappropriately vs. handing off cleanly — the turn-taking metric we implement in Phase 3 (FullDuplexBench-style).

**Why full-duplex models change the frame:** Moshi-class models don't *have* turns. The model
consumes the user's audio stream and produces its own **at the same time, every ~80ms frame**.
"Should I speak now?" stops being an engineered if-statement around a VAD and becomes something
the model learned from real conversation data. Interruption recovery and backchanneling fall out
of the architecture instead of being bolted on.

**Why neural audio codecs matter (Mimi, in Moshi's case):** LLMs eat tokens, not waveforms. A
codec like Mimi compresses audio into discrete tokens at a low frame rate (12.5 Hz) with a
*causal/streaming* design — no lookahead — so the model can process audio as it arrives.
Codec frame rate sets the floor on conversational latency. This is the deepest architectural
difference from cascade-land, where audio↔text conversion happens at turn boundaries.

- [ ] I can explain where each chunk of a cascade's 1-2s dead air comes from
- [ ] I can explain why CSM-1B alone can't power a full-duplex agent (see DECISIONS.md 0003)
- [ ] I can explain what a streaming neural codec is and why its frame rate bounds latency

**Reading (optional, ranked):** Moshi paper (Kyutai, 2024) — read §1-3 for the dual-stream idea;
Mimi codec section of the same paper; FullDuplexBench (2025) for turn-taking metrics.

---

## Lesson 1 (Phase 1) — Running a full-duplex model locally *(unlocks after Phase 1)*
## Lesson 2 (Phase 2) — Hybrid intelligence: fast mouth, slow brain *(unlocks after Phase 2)*
## Lesson 3 (Phase 3) — Measuring conversation: latency, Takeover Rate, blind evals *(unlocks after Phase 3)*
## Lesson 4 (Phase 4) — Real-time audio in production: WebRTC, SFUs, and cost control *(unlocks after Phase 4)*
## Lesson 5 (Phase 5) — Shipping and positioning an OSS infra project *(unlocks after Phase 5)*
