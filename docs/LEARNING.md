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

## Lesson 1 (Phase 1) — Full-duplex in code: a walkthrough of `agent/duet_agent/local_loop.py`

Open [`agent/duet_agent/local_loop.py`](../agent/duet_agent/local_loop.py) side-by-side with this.
It's ~250 lines and there is no magic left once you've traced one 80 ms frame through it.

### The system's heartbeat is a codec frame, not a "turn"

Everything is built on one constant: `FRAME_SIZE = 1920` samples at 24 kHz = **80 ms**. That's
one frame of the **Mimi** neural codec. Mimi compresses each 80 ms of audio into **8 discrete
tokens** (8 parallel "codebooks": the first captures semantics/phonetics, the rest stack acoustic
detail — voice timbre, prosody). So from the model's point of view, a conversation is not text
turns — it's two synchronized token streams ticking along at 12.5 frames/sec.

### Where the model listens while it speaks

The entire full-duplex mechanism is `step_once()` — three lines matter:

```python
codes = mx.array(user_frame).transpose(1, 0)[:, :8]   # YOUR last 80ms, as tokens, going IN
text_token = gen.step(codes)                           # one transformer step consumes them...
audio_tokens = gen.last_audio_tokens()                 # ...and emits ITS next 80ms, coming OUT
```

One `gen.step()` call = the model *hears* your latest frame AND *produces* its own next frame.
It runs **every 80 ms, unconditionally, forever**. When Moshi "isn't talking," it's still
generating audio tokens — they just decode to silence. When you "aren't talking," your mic is
still feeding it tokens — of your room tone, your breathing, your "hmm". Both channels are
always hot. That's the definition of full-duplex, and notice what's absent: there is no VAD,
no endpointing, no `if user_is_done_speaking:` anywhere in the repo.

### So where is the interruption handler?

**There isn't one — and that's the profound part.** Trace what happens when you barge in while
Moshi is mid-sentence:

1. Your voice hits `on_mic()`, which has a load-bearing comment: the mic path **never gates**,
   not even while Moshi is speaking (a cascade would mute or discard this audio).
2. 80 ms later your tokens are inside `gen.step()`. The model's context now contains
   "I was saying X *and simultaneously* the human started saying Y over me."
3. The model was trained on thousands of hours of real overlapping conversation, where the
   statistically likely continuation of "other speaker barged in" is: trail off, go quiet,
   listen, maybe say "oh—sorry, go ahead." So the *most probable next audio tokens for its own
   stream* are exactly that. Interruption recovery is next-token prediction, not an event handler.

The same explains backchannels: mid-way through *your* long sentence, the likeliest continuation
of *Moshi's* stream is a short "mm-hm" — so it emits one, without taking the floor.

### The text stream you see scrolling: the "inner monologue"

`gen.step()` also returns a text token each frame (usually padding, ids 0/3). Moshi predicts the
words it's about to say *slightly ahead of* the audio — text acts as scaffolding that keeps the
audio coherent. Printing it (`print(piece, end="")`) gives you a live transcript of the agent's
own speech for free. **Remember this stream — in Phase 2 it becomes the hook where the async
reasoning layer reads what's being discussed and injects knowledge back in.**

### Why two processes and four relay loops

Real-time audio is a hard-deadline system: `model_process` must finish every step in <80 ms,
and `audio_process` must hand the sound card a buffer every 80 ms, *no matter what*. Python's
GIL means one slow step could starve the audio callback if they shared a process, so they're
separated and speak one-frame-at-a-time over queues. The four little async loops in
`audio_process` are just plumbing between the sync sound-card callbacks, the Rust codec's
worker threads, and the model queue. If the model ever misses its budget, `on_speaker()`
plays silence instead of glitching, and counts it as a lag — you'll see the count on exit.

### What "latency" means here

A cascade's latency is `endpoint-wait + ASR + LLM + TTS` ≈ 1-2.5 s. Moshi's floor is
**one codec frame (80 ms) + one model step (measured on this machine — see the benchmark
numbers in DECISIONS.md 0004)**, because reacting to you IS generating the next frame. The
p95 step time printed on exit is the number that must stay under 80 ms — that's the real-time
constraint everything else in this project serves.

- [ ] I can trace one 80 ms frame: mic → Mimi encode → `gen.step` → Mimi decode → speaker
- [ ] I can explain why there is no interruption handler and why that's not a bug
- [ ] I can explain what the inner-monologue text stream is and why it exists
- [ ] I know which number on the exit report proves the loop runs in real time


## Lesson 2 (Phase 2) — Hybrid intelligence: fast mouth, slow brain *(unlocks after Phase 2)*
## Lesson 3 (Phase 3) — Measuring conversation: latency, Takeover Rate, blind evals *(unlocks after Phase 3)*
## Lesson 4 (Phase 4) — Real-time audio in production: WebRTC, SFUs, and cost control *(unlocks after Phase 4)*
## Lesson 5 (Phase 5) — Shipping and positioning an OSS infra project *(unlocks after Phase 5)*
