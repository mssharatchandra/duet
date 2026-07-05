# Benchmark results — Duet (full-duplex) vs cascaded baseline

**Run: 2026-07-05 · Apple M5 24 GB · 10 scenarios × 2 systems · same simulated caller (Piper),
same brain (gemini-3.1-flash-lite), same SDR persona.** Reproduce:
`uv pip install -e 'agent[bench]' && python eval/bench/run_bench.py` (~15 min, needs
`GEMINI_API_KEY`). Raw per-call data: `out/calls.jsonl` · audio: `out/clips/*.wav`.

## Headline numbers

| mode | calls | takeover rate | backchannels/call | handoff p50 | handoff p95 | overlap | $/min |
|---|---|---|---|---|---|---|---|
| duet | 10 | 0.24 | 0.4 | **240 ms** | 3,248 ms | 0.234 | $0.0081 |
| cascade | 10 | **0.00** | 0.0 | 1,880 ms | **2,204 ms** | **0.053** | **$0.0003** |

## Honest reading — both directions

**Where Duet wins.** Median perceived response time is **~8× faster** (240 ms vs 1,880 ms —
human-conversation territory vs walkie-talkie territory), and Duet backchannels ("mm-hm")
while the caller speaks, which a cascade cannot do at any price.

**Where Duet loses.** Moshi is an *eager* listener: it grabbed the floor mid-utterance in 24%
of caller turns (cascade: never), overlapped caller speech 4× more, and its p95 handoff
(3.2 s — the occasional long pause before responding) is *worse* than the cascade's tail.
Full-duplex trades "never interrupts" for "sometimes interrupts like a pushy human." Whether
that nets out more natural is exactly what the blind listening test measures
([docs/BLIND_EVAL.md](../../docs/BLIND_EVAL.md)) — **human naturalness delta: not yet measured.**

**Metric bias, disclosed.** "Takeover" = agent speech *starting* inside a caller utterance. A
cascade can never score a takeover by construction (it only *continues* talking through a
barge-in — for our modeled 400 ms; that rudeness lands in overlap, not takeovers). The metric
is therefore biased **against** Duet, which is the acceptable direction of unfairness.

**Cost, disclosed.** Duet's $/min prices the M5's work at a declared serverless-GPU rate
(`GPU_USD_PER_HOUR=0.40`, L4-class). The cascade ran free CPU ASR/TTS in-process; a hosted
production cascade would pay vendor ASR/TTS/LLM per minute instead — typically $0.01-0.05/min
at 2026 list prices. Neither number includes serving overhead. Treat both as
order-of-magnitude, not quotes.

## Method (constants you may disagree with — rerun with your own)

- **Duet: measured, not simulated.** Caller audio is fed into Moshi's real input; output
  audio is energy-detected on the same 80 ms grid. One turn per scenario barges in while the
  agent is audibly speaking.
- **Cascade: real component latencies** (faster-whisper base.en int8 · same Gemini brain ·
  Piper synthesis, first-chunk measured) on a simulated timeline **plus declared constants**:
  `ENDPOINT_WAIT_S = 0.7` (silence endpointing), `BARGE_KILL_S = 0.4` (barge-in TTS cutoff).
- Definitions of takeover / backchannel / handoff / overlap: header of
  `agent/duet_agent/turntaking.py`.
