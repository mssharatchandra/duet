# Duet — handoff prompt for another LLM/engineer

*Written 2026-08-01. Self-contained: assumes zero prior context. Copy this whole file as a prompt.*

---

## Who you are and what you're inheriting

You are taking over **Duet**, an open-source full-duplex voice AI agent:
https://github.com/mssharatchandra/duet (Apache-2.0, public). Local checkout at
`~/Downloads/CURIOUS/duet` on an Apple M5 / 24 GB Mac.

The owner is an engineer who is **new to real-time speech AI specifically** and is using this
project to go from novice to genuinely expert. So there are two deliverables at all times: a
working artifact, and an honest explanation of *why* it works. `docs/LEARNING.md` (a lesson per
phase), `docs/blog/voice-ai-the-80-20.md` (the field in one post), and `docs/DECISIONS.md` (a dated
engineering journal, ~14 entries) are first-class outputs, not documentation chores.

**The single most important cultural rule: never make a claim you did not measure, and publish the
results that make you look bad.** DECISIONS.md entry 0012 exists because an eval disproved two of
my own earlier claims; 0013 exists because a later eval reversed 0012. That is considered success
here. If you find yourself writing "this should be faster" — go measure it or delete the sentence.

---

## The thesis in one paragraph

Nearly all production voice agents are **cascades**: `mic → VAD → ASR → LLM → TTS → speaker`, run
in strict turns. Each stage is fine; the composition is what feels robotic, because silence-based
endpointing must *wait* to know you finished. Measured in this repo: **1,880 ms median response**.
Humans reply in ~200 ms and constantly overlap. **Full-duplex models** (Kyutai's Moshi is the only
production-grade open one) delete the concept of a turn: one model step per 80 ms frame
simultaneously consumes the user's audio and emits the agent's own. There is **no interruption
handler anywhere in the codebase** — when you barge in, your tokens enter the model's context and
the likeliest continuation of its own audio stream is to trail off. Interruption recovery is
next-token prediction. Duet measures 240 ms median response and real backchannels.

---

## Architecture as built

```
80 ms hard-real-time loop                    async brain (~1s, never blocks)
─────────────────────────                    ────────────────────────────────
mic → Mimi codec → gen.step() → Mimi → spk   user audio → faster-whisper (ASR)
                      ▲                                 → Gemini Flash (persona)
                      └── on_text_hook ◄── injector ◄── talking point
```

- **Duplex core**: Moshi (`kyutai/moshiko-mlx-q4`) via MLX on Apple Silicon. One `gen.step()` per
  1920-sample / 80 ms frame at 24 kHz. Mimi codec = 8 tokens per frame per direction.
- **Async brain**: `gemini-3.1-flash-lite` (~1.0–1.3 s). Fired on a daemon thread; the audio loop
  polls non-blocking once per frame. If it dies, Moshi keeps talking — degradation is "less
  substantive," never dead air.
- **Injection**: `LmGen(on_text_hook=…)` hands you the sampled text token *before* that frame's
  audio is generated from it. Overwrite it → Moshi speaks your word in its own voice. This is
  Kyutai's own TTS forcing mechanism repurposed. Governed by three etiquette rules in
  `injector.py`: never inject over the user; barge-in **drops** the remaining script (never
  pause/resume); guidance older than 8 s is discarded.
- **ASR feeds the brain, not the mouth.** It is not a return to cascade-land; the audio loop never
  waits on it.

### Repo map

| Path | Contents |
|---|---|
| `agent/duet_agent/local_loop.py` | The annotated full-duplex loop (also LEARNING Lesson 1) |
| `agent/duet_agent/injector.py` | Text-stream injection + etiquette rules |
| `agent/duet_agent/reasoning.py` | Async Gemini layer, stdlib-only transport, fail-silent |
| `agent/duet_agent/persona.py` | SDR persona, fact sheet, **deterministic** BANT scoring |
| `agent/duet_agent/turntaking.py` | Takeover / backchannel / handoff / overlap metrics |
| `agent/duet_agent/tts.py` | Pluggable streaming TTS (piper / kokoro / chatterbox) |
| `agent/duet_agent/telemetry.py` | Langfuse traces + Postgres call records, fail-silent |
| `eval/bench/run_bench.py` | Three-way harness: `duet` / `cascade` / `hybrid` |
| `eval/asr/` | WER × condition matrix, 4 engines, augmentation |
| `eval/reasoning/` | 12-scenario golden eval, CI-gated ≥90% |
| `web-demo/` | aiohttp + WebSocket + AudioWorklets browser demo, session capture |
| `infra/` | Docker: Langfuse, Grafana, Prometheus, Loki, Postgres |
| `docs/` | DECISIONS (journal), LEARNING (curriculum), blog, BUILD_WORLDCLASS, HERMES_VOICE_MVP |

Run: `cd agent && uv run duet-local` (raw duplex) · `uv run duet-sdr` (scripted SDR, no mic) ·
`agent/.venv/bin/python web-demo/server.py` → http://localhost:8990 · `./scripts/local-demo.sh`
(observability stack + logins).

---

## Everything measured so far

**Duplex core** (M5, q4, quiet machine): model step p50 **48 ms** / p95 **51 ms** against the
80 ms budget. Peak 4.6 GB RSS / 5.2 GB Metal. Cold start ~2 s. q8 sounds slightly better but
measures p95 **91 ms** — over budget, so it stutters; q4 stays default. **Smoothness beats bits.**

**Turn-taking, 10 scenarios, same simulated caller and same brain both sides:**

| | takeover rate | backchannels/call | handoff p50 | handoff p95 | overlap | $/min |
|---|---|---|---|---|---|---|
| duet (full-duplex) | **0.24** ❌ | 0.4 | **240 ms** ✅ | 3,248 ms | 0.234 | $0.0081 |
| cascade baseline | 0.00 | 0.0 | 1,880 ms | 2,204 ms | 0.053 | $0.0003 |
| hybrid (1 scenario only) | 0.00 | 0.0 | **80 ms** | **9,656 ms** ❌ | 0.043 | $0.0085 |

**ASR** (WER, augmented matrix, byte-identical audio, single process):

| model | clean | snr10 | snr5 | max RTF |
|---|---|---|---|---|
| base.en | 4.2% | 7.6% | 14.1% | 0.30x |
| small.en ← current default | 3.0% | 4.9% | 8.7% | 1.42x ⚠️ |
| mlx-whisper-large-v3-turbo | 2.3% | 1.9% | 3.4% | 0.87x |
| parakeet-tdt-0.6b-v3 | **1.9%** | 2.7% | **2.7%** | **0.08x** |

**TTS**: piper TTFB p50 **83 ms**, kokoro **380 ms**, chatterbox **fails to load** (broken `perth`
watermarker dependency — documented, not fought). TTFB is the metric that matters, not RTF.

**Reasoning eval**: 12 scenarios × ~3.4 structured checks (intent, objection class, fact grounding,
two anti-hallucination canaries, brevity, BANT signals). CI gate ≥90%; last run **97.6%**.

**Tests/CI**: 77 unit tests, ruff (line-length 130), CI on ubuntu (proves brain modules are
stdlib-pure) + macOS arm64 (full MLX), plus a live golden eval on push and an infra smoke workflow.
Moshi weights deliberately **not** pulled in CI (5 GB/commit); `duet-sdr` scripted mode is the local
pre-push gate.

**Spend so far: $0.00** (Gemini free tier; everything else local/OSS).

---

## Why it sucks — read this section twice

This is the honest critique. Do not soften it; fix it or account for it.

1. **The voice is genuinely bad.** Robotic timbre. This is the #1 user complaint and it is a model
   ceiling (≈1B-param decoder, streaming-tuned codec bitrate, 4-bit quantization), not a bug you
   can fix locally. Today you choose between the most human *voice* and the most human *timing*.

2. **Injected speech sounds rushed and spliced.** Forcing tokens bypasses Moshi's own prosody — the
   model didn't "decide" to say those words, so the seams are audible. `pace_pads=2` (inserting pad
   "breaths") helps but is a workaround, not a fix.

3. **It interrupts the user in ~1 of 4 turns** (takeover 0.24 vs cascade's 0.00). By the project's
   own metric, Duet is ruder than the thing it claims to beat. This is the most important
   unfixed defect and the obvious next project (semantic turn detection / a smarter oracle).

4. **The entire benchmark is synthetic.** A Piper-TTS "caller" reads scripted turns. Clean,
   unaccented, noiseless, no crosstalk. Real conversation looks nothing like this.

5. **The Delta-4 blind human evaluation — the honesty premise of the whole project — has never been
   run.** Zero humans have rated anything. `docs/BLIND_EVAL.md` has the protocol and
   `eval/bench/out/clips/` has the audio; nobody has recruited raters. Every claim about
   "naturalness" is therefore unearned and the README says so.

6. **The ASR eval was wrong twice** (0012 chose a default from an eval that couldn't discriminate;
   0013 reversed it) and is *still* not on-distribution. Session capture now works and exactly
   **one** real utterance has been recorded. One utterance is not a dataset.

7. **Resource contention breaks the system, repeatedly** — three times now, including live during
   a user demo (an eval at ~300 % CPU pushed model step p95 to 402 ms against an 80 ms budget;
   audio turned to stutter). There is **no admission control**: nothing detects a busy machine,
   sheds load, or warns before quality collapses. In production this is a P0.

8. **The hybrid is bimodal and unreliable.** Median 80 ms (excellent) but p95 9.6 s, and one run
   produced *zero* speech because the oracle never fired. Needs a timeout fallback.

9. **Nothing is deployed. There is no public URL.** Phase 4 (LiveKit transport, Caddy/TLS, email
   gate, server-side session caps, consent + audit log, rate limiting, GPU autoscaling) is fully
   designed and **entirely unbuilt**. The "drop-in / deployable" framing is unproven.

10. **Cost numbers are modeled, not billed.** `$/min` uses a *declared* `GPU_USD_PER_HOUR=0.40`.
    The system has never run on a rented GPU, never served concurrent users, never been load-tested
    (k6 is in the plan, unwritten).

11. **Single-user by construction.** The web server accepts one session at a time, has no auth, no
    rate limiting, and binds localhost. Fine for a demo; nowhere near a product.

12. **The observability stack is absurdly heavy for the payload.** ClickHouse + Langfuse + Grafana
    + Prometheus + Loki + Postgres — ten containers — to trace ~4 LLM calls per conversation. It's
    also what caused defect #7. Right tool, wrong scale.

13. **Test coverage is lopsided.** 77 tests, but concentrated on pure logic (injector, turn-taking,
    persona, capture). The audio loop — the hardest and most bug-prone code — is barely tested
    automatically because it needs 5 GB of weights.

14. **Nobody has ever cloned this fresh.** No Dockerfile for the agent, no packaged install. The
    "reproducible in under 30 minutes from a clean clone" goal is asserted, never verified.

15. **The docs may be better than the product.** The writing is extensive and honest; the actual
    experience of talking to it is poor. Guard against this becoming a beautifully documented
    mediocre demo. Ship improvements to the *experience*, not just to the journal.

16. **Secrets hygiene**: a Gemini API key was shared via screenshot and lives in `.env` + a GitHub
    Actions secret. It should be rotated before any public launch.

---

## Direction and vision

**Near-term, in priority order:**

1. **Fix takeover rate 0.24 → <0.10** while holding handoff p50 < 300 ms. This is the defining
   defect. Candidates: semantic turn detection (`pipecat-ai/smart-turn`, BSD-2), tuning the hybrid
   oracle, or a VAP-style turn-taking head. The harness can adjudicate any of them.
2. **Finish the three-way experiment** (`duet,cascade,hybrid` × 10 scenarios) and publish the table
   including the hybrid's ugly p95. A run was in flight at handoff — check
   `eval/bench/out/summary.md` and `calls.jsonl`.
3. **Make the ASR eval real**: several minutes of the owner's actual microphone audio via the
   web demo's capture toggle, corrected in the review panel, then re-run `--augment`. Only then
   decide base/small/parakeet. Note parakeet runs on the *same Metal GPU* as Moshi — its 0.08x RTF
   was measured without Moshi running, so contention is untested.
4. **Run the blind human eval.** Five raters, ten minutes each. This is the project's own stated
   standard and it is embarrassing that it hasn't happened.
5. **OpenAI adapters as the quality ceiling** — the owner has an API key. `whisper-1` /
   `gpt-4o-transcribe` for ASR, `gpt-4o-mini-tts` for TTS, plus the Realtime API as a fourth
   benchmark arm. Wire them as swappable backends *measured by our harness*, not as a silent
   upgrade: the point is to quantify what commercial quality costs in latency, money and privacy.

**The strategic pivot worth taking seriously** (`docs/HERMES_VOICE_MVP.md`): the owner has a
separate private repo, `hermes-brain` ("brain of my personal AI"), which already computes a
spaced-repetition schedule (`review_intervals_days: [1,3,7,14,30,90]`) and ships a `recall.md` per
learning run. The content and schedule exist; only the *interface* is missing. **Full-duplex spoken
recall over your own knowledge base** — a tutor you can interrupt, that stays quiet while you
struggle — is a genuinely novel personal product, runs local-first for ~$1/month versus $48–90 for
commercial voice platforms, and closes hermes-brain's own loop. Its README explicitly invites this:
"models and harnesses are replaceable executors."

**The broader contribution** (`docs/BUILD_WORLDCLASS.md`): voice AI has **no eval culture**. Text
agents have SWE-bench and trace viewers; voice agents ship on "it felt laggy." Nobody reports their
takeover rate. The turn-taking harness here may be more valuable than the agent — packaging it as
a standalone `voice-evals` tool with pluggable adapters is the differentiated play.

**Deployment insight worth preserving**: for a *personal* agent the enemy is **idle time, not
per-minute inference**. An always-on cloud GPU at $0.40/hr is $292/month — worse than ElevenLabs —
because you talk 20 minutes a day and pay for 1,440. Serverless scale-to-zero fixes the bill but
adds a 10–30 s cold start. **Local-first on owned hardware wins on cost, latency and privacy
simultaneously.**

---

## House rules

- **Measure, then claim.** Publish unflattering results. Correct the journal when you're wrong.
- **Nothing external in the 80 ms loop.** No API, no MCP, no network call. Ever. MCP belongs in the
  async brain; integrations belong at the transport layer.
- **One sample rate end to end** (24 kHz). The one place this was violated caused a silent bug.
- **`caffeinate` every long-running job on this Mac** — sleep has killed a benchmark and an 8 GB
  download. And **never run a heavy job while someone is talking to the demo** (defect #7).
- Comments explain *why*; the code doubles as teaching material. ruff line-length 130.
- `agent/.venv/bin/ruff check` + `agent/.venv/bin/pytest -q agent/tests` before every commit.
- Ask before spending money above ~$20; keep the running total in DECISIONS.md.
