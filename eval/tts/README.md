# TTS benchmark — the quality voice tier

Measured 2026-08-01 on an Apple M5 (24 GB), CPU/MPS, over utterances from
`eval/bench/scenarios.json`. Reproduce:

```bash
agent/.venv/bin/python -u eval/tts/bench_tts.py
```

## Results

| backend | TTFB p50 | TTFB p95 | RTF | load |
|---|---|---|---|---|
| **piper** | **83 ms** | 114 ms | 0.03x | 11.2 s |
| **kokoro** | 380 ms | 700 ms | 0.12x | 7.9 s |
| chatterbox | — | — | — | ❌ fails to load (see below) |

## Why TTFB is the headline and RTF is the footnote

Time-to-first-byte is what a caller experiences as "how long before it started
talking." Total synthesis time (RTF) only decides your compute bill. Both
backends here are far under 1.0x RTF, so neither is throughput-limited; they
differ by **4.6x on the number that actually matters**.

What that means in each architecture:

- **In a cascade**, TTS TTFB lands directly on top of endpoint-wait + ASR + LLM.
  Kokoro's 380 ms is a real, audible addition there; Piper's 83 ms is not.
- **In Duet's hybrid** (`eval/bench/run_bench.py --modes hybrid`), the talking
  point is synthesized the moment the brain returns it — roughly a second
  before the turn-taking oracle fires — so **TTFB is masked entirely** and you
  can afford the better-sounding voice for free. That masking is the point of
  the architecture, and it is why "which TTS is fastest" is the wrong question
  for us; "which sounds best while still fitting inside the mask" is the right one.

## What this harness does NOT measure

**Voice quality.** That is a human judgment and no number here captures it.
Listen to `samples/*.wav` and decide for yourself — Kokoro is widely considered
to sound better than Piper, which is exactly the tradeoff the TTFB column
prices. A proper comparison belongs in the blind listening protocol
(`docs/BLIND_EVAL.md`), not in this file.

## Chatterbox: documented failure, not a verdict

`chatterbox-tts` 0.1.7 installs cleanly and imports, but constructing the model
raises `TypeError: 'NoneType' object is not callable` at
`chatterbox/tts.py:126`, where `perth.PerthImplicitWatermarker()` is called.
Installing `resemble-perth` does **not** fix it: the `perth` package imports,
but `perth.PerthImplicitWatermarker` is itself `None`, so its own `__init__`
is failing to expose the class (an unmet sub-dependency). The watermarker is
mandatory in `ChatterboxTTS.__init__`, so the model cannot be constructed at
all on this machine.

This is a broken transitive dependency in Chatterbox's stack, not an
incompatibility with Duet. It was timeboxed and recorded rather than fought —
Chatterbox remains the most interesting candidate on paper (MIT, claimed
sub-200 ms) and is worth retrying on a future release.
