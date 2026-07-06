# Voice AI: the 80% you need, for 20% of the effort

*Everything in this post was measured, built, or broken for real in the [Duet repo](https://github.com/mssharatchandra/duet) — an open-source full-duplex voice agent built from scratch. No numbers are quoted from vendor marketing; the embarrassing ones are included on purpose.*

---

## 1. The one mental model: voice AI is latency engineering wearing an AI costume

Humans respond to each other in about **200 milliseconds** — and frequently *overlap*: we "mm-hm" while the other person talks, we finish each other's sentences, we barge in. Every voice AI system you've ever found robotic fails not because its words are dumb, but because its **timing** is wrong. It waits too long, never overlaps, resumes a canned pitch after you interrupt it.

So here is the field in one sentence: *a voice AI system is a hard real-time system (audio deadlines measured in tens of milliseconds) wrapped around models whose latencies are measured in seconds, and the entire craft is hiding that mismatch.*

Everything below is a consequence of that sentence.

## 2. The cascade: how ~95% of production voice AI works

The standard architecture is a **cascaded pipeline**:

```
mic → VAD → ASR → LLM → TTS → speaker
      (voice   (speech   (the    (text to
      activity  to text)  brain)  speech)
      detection)
```

Each stage is excellent in isolation. The composition is what kills naturalness, because the stages run in **series**, and each contributes latency *after you stop talking*:

| Stage | What it's doing | Typical cost |
|---|---|---|
| **Endpointing** | Waiting for silence to decide you're *done* | **500–800 ms** — a deliberate wait, not compute |
| ASR finalization | The transcript stops changing | 100–300 ms |
| LLM first token | The brain starts answering | 200–800 ms |
| TTS first byte | Audio starts coming out | 100–300 ms |

Total: **1–2.5 seconds of dead air**, every turn. We built this exact pipeline as our benchmark baseline (faster-whisper → Gemini Flash → Piper, all open source) and measured **1,880 ms median response time**. That's not a bad implementation — that's the architecture. The walkie-talkie feel *is* the block diagram.

Note the deepest problem: **endpointing is unfixable within the paradigm.** A silence-based endpointer must wait to know you finished — wait less and it interrupts you mid-thought; wait more and it feels dead. Smarter "semantic VAD" (predicting completion from *content*) helps, but the turn boundary itself remains the architecture's atomic unit. The cascade cannot backchannel — there is no "during your turn" in its world model.

Also learn the word **barge-in**: the user interrupting the bot. A cascade handles it by killing TTS playback and throwing away state — the bot doesn't know how much of its sentence you actually heard.

## 3. Full-duplex models: deleting the concept of a turn

The 2024–25 generation of native speech models (Kyutai's **Moshi** is the open flagship) made a structural move: instead of converting between audio and text at turn boundaries, the model consumes the user's audio stream and produces its own **simultaneously, forever**. There are no turns anywhere in the architecture.

Three ideas make this work, and they're the 80/20 of understanding any modern speech model:

**(a) Neural audio codecs — the load-bearing wall.** Transformers eat discrete tokens, not waveforms. A codec like Mimi compresses each **80 ms** of audio into **8 tokens** (parallel "codebooks": the first carries semantics/phonetics, the rest stack acoustic detail — timbre, prosody). Crucially it's *causal* — no lookahead — so audio can be tokenized as it arrives. **The codec's frame rate is the floor on your conversational latency.** 12.5 Hz frames = the model can react, at the physics level, 80 ms after you do.

**(b) Two streams, one transformer.** Moshi models the user's token stream and its own as parallel sequences. One `step()` per frame both *hears* your last 80 ms and *emits* its next 80 ms. When the model "isn't talking," it's still generating tokens — they just decode to silence. When you "aren't talking," it's still hearing your room tone. Both channels are always hot. That is the literal meaning of full-duplex.

**(c) The inner monologue.** The model also predicts a text stream slightly *ahead* of its own audio — text as scaffolding that keeps 1B-parameter speech coherent. This stream turns out to be the most useful integration surface in the whole system (see §5).

The consequence that should rearrange your intuitions: **there is no interruption handler.** We grepped for one; it doesn't exist. When you barge in mid-sentence, your tokens change the model's context, and the statistically likely continuation of *its own* audio stream — learned from thousands of hours of real overlapping conversation — is to trail off and listen. Interruption recovery is next-token prediction. Backchannels ("mm-hm" during *your* sentence) fall out the same way. We measured our loop at **240 ms median response** — 8× faster than our cascade, in human territory.

## 4. The hybrid: fast mouth, slow brain

Here's the catch that keeps cascades employed: full-duplex models are conversationally brilliant and **factually useless**. Moshi cannot reliably quote your pricing page; it rambles; you cannot keep it on script. Meanwhile the models that *can* reason (frontier LLMs) take ~a second — 12 frames of dead air.

The production answer is the **hybrid / async-augmentation pattern** (Kyutai's own `moshi-rag` sketched it): split responsibilities by *latency class*.

| | Owns | Budget |
|---|---|---|
| **Fast mouth** (duplex model) | timing, backchannels, interruptions, filler, tone | 80 ms, hard |
| **Slow brain** (LLM, async) | facts, objection handling, qualification logic | ~1 s, soft |

The audio loop **never waits** for the brain. It fires an async request when the user says something substantive and polls (non-blocking, once per frame) for the answer. Until guidance lands, the mouth free-runs — it acknowledges, hums, holds the floor. A 1.3-second LLM round trip is *completely masked*; the caller hears a person taking a beat. If the LLM times out entirely, nothing breaks — the conversation just gets less substantive. Degradation is "chattier, dumber," never "dead air." We measured Gemini Flash-Lite at ~1.0–1.3 s per call, fully hidden.

**How does the brain's answer get into the mouth?** The elegant trick: the generation loop exposes a hook on the text stream — you can *overwrite the sampled text token* before the audio for that frame is generated from it, and the model speaks your word in its own voice and prosody (this is the same mechanism Kyutai's own TTS uses for script-forcing). Queue a tokenized sentence, feed one token per frame, and the brain literally speaks through the mouth.

The etiquette rules around injection are where naturalness lives (we shipped exactly three):

1. **Never inject over the user** — wait for a word boundary *and* ~0.5 s of user silence. Slow guidance thus sounds like thinking, not buffering.
2. **The user always wins** — barge-in *drops* the rest of the script (never pause/resume; resuming a pitch after an interruption is peak robot).
3. **Guidance expires** — a talking point that waited 8 s unspoken is stale; discard it.

And a confession that teaches a real lesson: our injected sentences sound *hurried*. Why? Natural Moshi speech interleaves pad tokens — micro-pauses — between words. Our injector force-feeds content tokens back-to-back, one per 80 ms frame, no breaths. The fix (interleave pads to mimic natural pacing) is known; the lesson is general: **when you bypass a generative model's own output distribution, you also bypass its prosody, and it shows.**

## 5. Turn-taking is measurable — so measure it

"More natural" is not a claim; it's a hypothesis. The field's benchmark direction (FullDuplexBench et al.) is to score **turn-taking mechanics** from two boolean tracks sampled on the frame grid — *user speaking?* / *agent speaking?*:

- **Handoff latency** — user stops → agent audibly starts. This is *perceived* response time. Define it once, measure both systems identically.
- **Takeover** — agent starts talking >0.6 s *inside* your utterance: the "shut up, I'm pitching" failure.
- **Backchannel** — same onset, but ≤0.6 s ("mm-hm"): the *good* overlap. A metric that counts all overlap as bad punishes exactly the behavior you want.
- **Overlap ratio** — fraction of your speaking time the agent talks over.

Our honest results, same scripted caller, same LLM brain, 10 scenarios each:

| | takeover rate | backchannels/call | handoff p50 | handoff p95 |
|---|---|---|---|---|
| Full-duplex | 0.24 | 0.4 | **240 ms** | 3,248 ms |
| Cascade | **0.00** | 0.0 | 1,880 ms | **2,204 ms** |

Read both columns. The full-duplex agent is 8× faster and actually backchannels — *and* it grabbed the floor in 24% of caller turns and has a worse worst-case tail. Full-duplex trades "never interrupts" for "sometimes interrupts like a pushy human." Whether that nets out more natural is a **human** question — which is why the final metric is a blind listening test (same conversations through both systems, raters who don't know which is which, 1–10 naturalness). Machines score mechanics; only blinded humans score feel. Publish whatever number comes out.

**Related discipline — evals for the brain:** a golden set of scenarios scored on structured checks (intent classification, fact grounding, brevity), gated in CI at a threshold, including **hallucination canaries**: questions about features the product *doesn't have*, where the only passing answer is a graceful decline. An eval you can't fail is marketing.

## 6. Production is where voice AI actually gets hard

Everything above runs in a notebook. The following is the 80/20 of what breaks when it meets reality — each item cost us real debugging time:

**The real-time budget is a physical law.** One 80 ms frame must be fully processed in <80 ms, at p95, forever. Our loop measured p50 48 ms / p95 51 ms — comfortable. Then one day it measured 250 ms and speech turned to garbage. Nothing in the code had changed…

**Your machine is part of the system.** The regression was: an analytics database (ClickHouse, part of our observability stack) idling at 72% CPU, a background model download hashing chunks, and a Docker VM — all stealing cycles until the model missed its deadline and the speaker starved. **Real-time inference and batch workloads don't share a box.** In production this is why the GPU worker is its own machine; on a laptop it means: stop the analytics stack before demos. Corollary from the same week: every long-running job on a Mac gets `caffeinate`, because system sleep killed both a benchmark and an 8 GB download.

**Quantization is a latency decision, not just a quality one.** 8-bit weights sound cleaner than 4-bit — and measured p95 **91 ms** against the 80 ms budget on our M-series machine, versus 4-bit's 50 ms. Missed deadlines mean stutter, and stutter is *far* more damaging to perceived quality than quantization noise. We shipped 4-bit. **Smoothness beats bits.**

**Pipeline your stages.** Our first web server ran encode → step → decode in series: 92 ms/frame, over budget — even though every stage individually fit. Encoding frame N while the model steps on frame N−1 bought back ~25 ms for the price of one frame of latency. Sum-of-stages vs max-of-stages is the whole game.

**Jitter buffers are non-negotiable.** Playing audio the instant it arrives converts every latency spike into an audible glitch. Hold ~4 frames (320 ms) before starting playback; re-arm after underruns; drop backlog beyond ~2 s to stay live. Constant small delay beats intermittent stutter, always.

**Echo cancellation, or your bot talks to itself.** On open speakers, the mic hears the bot's own voice; a full-duplex model will happily respond to itself. Raw audio APIs give you nothing. The browser gives you **AEC + noise suppression free** via `getUserMedia` — one of several reasons production voice runs over **WebRTC** (browser/phone → SFU like LiveKit → your agent) rather than raw sockets: echo cancellation, jitter handling, NAT traversal, TLS, and resampling all come with the transport.

**Keep one clock.** We ran the browser's AudioContext at 24 kHz — the model's native rate — so one WebSocket binary frame = one 1920-sample codec frame, and *no resampling exists anywhere in the system*. Every resample point is a place for drift, latency, and bugs.

**Observability is three different questions.** Traces (Langfuse: what happened in *this* call — every LLM input/output/token/latency), metrics over time (Postgres + Grafana: is takeover rate drifting? what's handoff p95 this week?), logs (Loki). Wire cost in from day one: GPU-seconds × a *declared* $/hr rate + LLM tokens at list price → **$/min**, per call, in the dashboard. Ours: ~$0.008/min full-duplex (GPU-priced) vs ~$0.0003/min cascade-on-CPU — with the caveat that a production cascade pays vendor ASR/TTS instead, typically $0.01–0.05/min. Nobody serious evaluates a voice stack without $/min.

**The boring safety rails are product features:** hard server-side session caps (also your GPU-cost ceiling), consent notice before recording, append-only audit log, rate limiting on anything public, and graceful fallback when the GPU backend dies. Scale-to-zero GPU (serverless providers) beats an always-on instance until you have real call volume — at ~$0.40/hr for an L4-class card, a capped 4-minute demo call costs about 2.7 cents of GPU.

## 7. Why open voice models still sound robotic (set expectations honestly)

Our agent's *timing* feels human; its *voice* does not. That's three stacked ceilings: a ~1B-parameter speech decoder (commercial TTS quality lives at larger scale and more data), a codec bitrate tuned for real-time streaming rather than fidelity, and 4-bit quantization. Sesame's CSM showed how startlingly human *generation* can be — but it's a context-aware TTS, not a full-duplex model (its famous demo wraps closed orchestration around it). Which crystallizes the current frontier tradeoff: **today you choose between the most human voice and the most human timing.** The teams that merge them win the next round.

## 8. The 10 things to remember (the 20% of the 20%)

1. Voice AI is **latency engineering**; humans respond in ~200 ms and overlap constantly.
2. The cascade's dead air is **architectural** — endpointing must wait for silence to know you finished.
3. Neural codecs turn audio into tokens; **codec frame rate is your latency floor**.
4. Full-duplex = both token streams always hot; **interruption handling is next-token prediction**, not an event handler.
5. Split by latency class: **fast mouth (80 ms, hard) + slow brain (1 s, async)** — and never let the mouth wait.
6. Naturalness lives in **injection etiquette**: never over the user, user always wins, guidance expires.
7. **Measure turn-taking** (handoff, takeover, backchannel, overlap) mechanically; measure *naturalness* only with blinded humans.
8. p95 < frame budget is a law; **smoothness beats bits**; pipeline stages; jitter-buffer playback.
9. Use **WebRTC** for transport (AEC free); one sample rate end to end; separate real-time inference from batch workloads.
10. Trace every call, publish **$/min**, cap sessions server-side, and put your failure numbers in the README.

---

*Want to go deeper? The repo's [LEARNING.md](../LEARNING.md) walks each concept against the actual code, [DECISIONS.md](../DECISIONS.md) is the unfiltered engineering journal — including everything that went wrong — and [eval/bench/RESULTS.md](../../eval/bench/RESULTS.md) has the full benchmark method. Steal this post's outline for your own intro; the numbers are reproducible from a clean clone.*
