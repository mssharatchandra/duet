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


## Lesson 2 (Phase 2) — Hybrid intelligence: fast mouth, slow brain

Full-duplex models are conversationally brilliant and factually useless: Moshi holds a natural
conversation but can't reliably quote your pricing page. Cascades are the opposite. The hybrid
pattern (Kyutai's own `moshi-rag` popularized it) splits the job by *latency class*:

| | owns | latency budget |
|---|---|---|
| **Fast mouth** (Moshi) | timing, backchannels, interruptions, filler, tone | 80 ms, hard |
| **Slow brain** (Gemini Flash via `reasoning.py`) | facts, objection handling, qualification | ~1 s, soft, async |

### The injection trick — read `injector.py` and `_make_hook` in `sdr_loop.py`

`LmGen` exposes `on_text_hook`: it hands you the text token Moshi *just sampled* for this frame,
**before** the audio for the frame is generated from it. Overwrite the token and the depformer
renders your word in Moshi's voice with natural prosody. Queue a whole tokenized sentence and feed
one token per frame → the brain literally speaks through the mouth. This is the same mechanism
Kyutai's own TTS uses for script-forcing, repurposed for live guidance.

### The three rules that make it feel human (the brief's "crux")

1. **Slow guidance never stalls the call.** The audio loop polls `brain.poll()` once per frame,
   non-blocking. Until guidance lands, Moshi free-runs — it acknowledges, hums, keeps the floor.
   A 1.3 s brain round-trip is *completely masked*; the lead just hears a person taking a beat.
2. **The user always wins.** Barge-in mid-injection *drops* the rest of the script (rule 2 in
   `injector.py`). Resuming a canned pitch after an interruption is peak robot; Duet never does.
3. **Guidance expires.** A talking point that waited >8 s for a polite slot is discarded — the
   conversation has moved on.

And the failure mode: if Gemini times out or 500s, a `ReasoningFailure` lands on the queue, gets
logged, and *nothing else happens* — Moshi keeps chatting unaided. Degradation is "less substantive,"
never "dead air." Watch it happen: `test_failure_path_is_graceful` in `tests/test_reasoning.py`.

### Where ASR belongs in a full-duplex world

The brain needs the lead's *words* (Moshi's text stream only carries Moshi's own speech), so
`--live` mode runs faster-whisper on the user's audio. Crucial architectural point: **ASR feeds the
brain, not the mouth**. In a cascade, ASR sits in the critical path — its latency is your response
latency. Here it can take two whole seconds and the conversation doesn't hiccup, because responding
was never its job.

### Separation of trust: why scoring is not the LLM's job

`persona.py` splits the persona into (a) a fact sheet the LLM must ground in, (b) prompts, and
(c) a **deterministic** BANT scoring rubric. The LLM reports evidence strength ("budget: weak");
Python computes the score. LLMs are good at reading signals and bad at consistent arithmetic —
put judgment in the model and math in code, and the eval can then test each separately.

### What the eval actually gates (run: `python eval/reasoning/run_eval.py`)

Structured checks per scenario — intent, objection class, *grounding* (must cite real facts), two
**hallucination canaries** (asks about payroll/hardware, which Brewline doesn't do — the model must
decline, not invent), brevity, signal tracking. Gate ≥90%; first real run 92.7%, and the three
failures are visible in CI logs instead of the checks being widened until green. An eval you can't
fail is marketing, not engineering.

- [ ] I can explain why brain latency is invisible to the lead (and when it wouldn't be)
- [ ] I can trace a talking point: Gemini JSON → `inject()` → pad-boundary → forced tokens → speech
- [ ] I can explain why barge-in *drops* rather than *pauses* the script
- [ ] I can explain why ASR here doesn't recreate a cascade


## Lesson 3 (Phase 3) — Measuring conversation: latency, Takeover Rate, blind evals *(unlocks after Phase 3)*
## Lesson 4 (Phase 4) — Real-time audio in production: WebRTC, SFUs, and cost control *(unlocks after Phase 4)*
## Lesson 5 (Phase 5) — Shipping and positioning an OSS infra project *(unlocks after Phase 5)*
