# Building a world-class voice agent from open source — a learner's roadmap

*Written 2026-07-07. Repo facts (stars, licenses, last-push dates) verified against the GitHub API
on that date; re-check before relying on them, this field moves monthly.*

## The honest boundary first

**You can build a world-class voice agent. You cannot train world-class weights.** Those are
different sentences, and confusing them is what makes people give up.

- **Out of reach on a laptop:** matching ElevenLabs-grade timbre or Whisper-scale robustness.
  That's millions of dollars of compute and licensed data. Not a skill gap — a capital gap.
- **Fully in reach:** the *system* around the models — latency budgets, turn-taking, interruption
  handling, streaming, degradation behavior, evaluation. This is where good and great voice agents
  actually diverge, and it is 100% engineering craft.

The encouraging part: the top labs' *systems* are not far ahead of what you can assemble from open
parts. Their moat is model quality and reliability at scale. A composed open stack, tuned well, can
feel *better* than a lazily-integrated commercial one — and you'll understand every millisecond of it.

## Licensing: the one trap to avoid while learning

Your earlier question about [Fish Audio](https://github.com/fishaudio/fish-speech) (31.8k★): its
**Fish Audio Research License** permits research and non-commercial use freely — so for learning,
it's fair game. The commercial restriction only bites if you later sell something.

But: **prefer MIT/Apache when the quality is comparable, even for learning.** Not out of purity —
out of optionality. A side project that turns into something real shouldn't need a rewrite.
[Chatterbox](https://github.com/resemble-ai/chatterbox) (25.8k★, **MIT**, actively pushed, claimed
sub-200 ms inference) is the default I'd reach for; use fish-speech when you specifically want to
study its architecture or its voice-cloning quality.

## The 2026 open stack (verified 2026-07-07)

| Layer | Pick | License | Why |
|---|---|---|---|
| **Full-duplex core** | [Moshi](https://github.com/kyutai-labs/moshi) (10.8k★) | Apache-2.0 | Still the only production-grade natively full-duplex open model; ~200 ms, runs on Mac/MLX and even iPhone 15 Pro |
| **Smart cascade** | [Unmute](https://github.com/kyutai-labs/unmute) (1.5k★, pushed 2026-07) | MIT | Kyutai's "make any text LLM listen and speak" — streaming STT + semantic VAD + streaming TTS. The best-engineered cascade to learn from |
| **Streaming STT/TTS** | [delayed-streams-modeling](https://github.com/kyutai-labs/delayed-streams-modeling) (3.0k★) | Apache-2.0 | The streaming-first architecture behind Unmute |
| **TTS (quality)** | Chatterbox (25.8k★) · [Higgs Audio](https://github.com/boson-ai/higgs-audio) (8.3k★) · [Orpheus](https://github.com/canopyai/Orpheus-TTS) (6.3k★) | MIT / Apache-2.0 | Chatterbox for realtime, Higgs for expressiveness |
| **TTS (fast/tiny)** | [Kokoro](https://github.com/hexgrad/kokoro) (8.2k★) 82M params | Apache-2.0 | Absurdly good per byte; fine on CPU |
| **TTS (study)** | fish-speech (31.8k★) | Research | Voice cloning quality; non-commercial |
| **Speech-native LLM** | [Qwen3-Omni](https://github.com/QwenLM/Qwen3-Omni) (3.9k★) · [Ultravox](https://github.com/fixie-ai/ultravox) (4.5k★) | Apache-2.0 / MIT | Audio *straight into* an LLM — no ASR, so tone and hesitation survive |
| **ASR** | faster-whisper · NVIDIA Parakeet | MIT | Parakeet for speed, Whisper for robustness |
| **VAD** | [Silero](https://github.com/snakers4/silero-vad) (9.8k★) | MIT | The default; tiny and fast |
| **Semantic turn detection** | [smart-turn](https://github.com/pipecat-ai/smart-turn) (1.5k★) | BSD-2 | Predicts turn-end from *content*, not silence — the single biggest naturalness lever in a cascade |
| **Orchestration** | [Pipecat](https://github.com/pipecat-ai/pipecat) (13.8k★) · [LiveKit Agents](https://github.com/livekit/agents) (11.6k★) | BSD-2 / Apache-2.0 | Don't rebuild transport, telephony, and plumbing |

## The build path — six projects, each teaching one hard thing

You already have #0 done, which is a bigger head start than you probably realize: a working
full-duplex agent, an async reasoning layer, and a turn-taking benchmark harness. Most people
learning voice AI never build the harness at all.

**1. Voice-quality tier (weekend).** Add Chatterbox or fish-speech as an alternative voice path,
driven from Moshi's inner-monologue text stream. Measure both with the harness you already have.
→ *Teaches:* streaming TTS chunking, time-to-first-byte, and viscerally: **timbre ≠ timing.** You
will watch your naturalness metrics get *worse* as the voice gets prettier. That lesson is worth
more than the feature.

**2. Semantic turn detection (weekend).** Replace silence-based endpointing with smart-turn or your
own VAP-style head. Measure handoff latency and takeover rate before/after.
→ *Teaches:* the highest-leverage fix in all of cascade-land, and why "wait for silence" is a bug
disguised as a design.

**3. Voice cloning + persona (weekend).** Clone a voice with fish-speech/Chatterbox; give the agent
a consistent identity.
→ *Teaches:* what actually controls timbre, prosody, and speaker identity in modern TTS.

**4. Speech-native LLM (1-2 weeks).** Wire Ultravox or Qwen3-Omni so audio goes *directly* into the
LLM. Compare against your ASR→LLM path on the same scenarios.
→ *Teaches:* what ASR throws away — sarcasm, hesitation, emotion, emphasis — and why speech-native
models are where the field is going.

**5. Train something small yourself (2-4 weeks).** Not a foundation model — a *head*. E.g. a
turn-taking predictor on frozen Moshi/Whisper features, or fine-tune a small TTS on one voice.
→ *Teaches:* the actual ML, at laptop scale: data pipelines, overfitting, eval discipline.

**6. Put it on a phone number (1 week).** Pipecat or LiveKit + SIP. Call it from your actual phone.
→ *Teaches:* 8 kHz telephony codecs, packet loss, jitter, DTMF, and why "works on my Mac" and
"works on a call" are different products. **This is the step that separates demos from systems.**

## The reading list (ranked, ~6 papers to real fluency)

1. **Moshi** (Kyutai, 2024) — dual audio streams + inner monologue + the Mimi codec. §1-3 is the
   single densest thing you can read in this field. You're already running it.
2. **dGSLM: Generative Spoken Dialogue Language Modeling** (Meta, 2022) — the ancestor: two-channel
   dialogue modeling with no text at all. Read it to see how old the full-duplex idea is.
3. **Voice Activity Projection** (Ekstedt & Skantze) — the academic backbone of turn-taking
   prediction. This is the theory behind project #2 above.
4. **SoundStream** (2021) / **EnCodec** (2022) — how neural audio codecs work: RVQ, streaming,
   the bitrate-vs-latency tradeoff. Everything downstream depends on this.
5. **AudioLM** (Google, 2022) — semantic vs acoustic tokens; why the hierarchy exists.
6. **FullDuplexBench** (2025) — how to *measure* turn-taking, which is the discipline most projects
   skip. Compare its definitions against the ones in `agent/duet_agent/turntaking.py`.

Then follow the labs, not the papers: Kyutai, Sesame, Fixie, Boson, Resemble, Qwen — their release
notes move faster than the literature.

## How you'll know you got there

Not by vibes. By the harness:

- **Handoff p50 < 300 ms** with **takeover rate < 0.10** — fast *and* polite. (Duet today: 240 ms
  handoff, 0.24 takeover. Fast, not polite. That gap is your next project.)
- **Blind naturalness ≥ 8/10** from people who don't know which system they're hearing.
- **It survives a real phone call** on a bad connection.
- **You can explain every millisecond** between someone stopping speaking and your agent starting.

That last one is the actual definition of expertise here — and it's why building the measurement
tools matters more than collecting the models.
