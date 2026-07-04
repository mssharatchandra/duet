# agent

Duet's duplex core. Phase 1 ships the minimal local full-duplex loop: Moshi (Kyutai) on
Apple Silicon via MLX, quantized to 4-bit, talking and listening in the same 80 ms frame.

## Run it (macOS, Apple Silicon, ≥16 GB)

```bash
# one-time: install uv if you don't have it → https://docs.astral.sh/uv/
cd agent
uv venv --python 3.12 && uv pip install -e .

# the demo — first run downloads ~4.2 GB of weights from HuggingFace
uv run duet-local
```

**Wear headphones.** The raw mic/speaker path has no echo cancellation, so on open speakers
Moshi hears its own voice and may respond to itself (WebRTC gives us echo cancellation for
free in Phase 4).

Talk to it. Interrupt it mid-sentence. Ctrl-C to stop — it prints per-step latency stats
and peak memory on exit. Sessions are capped at ~5.3 minutes (`--steps 4000`, the KV-cache
length).

No mic handy, or want the performance numbers only:

```bash
uv run duet-local --headless 100   # benchmark 100 frames (8 s of simulated conversation)
```

Options: `-q 8` for higher-quality 8-bit weights (~8 GB), `--bf16` for full precision (~16 GB).

## What to read

[`duet_agent/local_loop.py`](duet_agent/local_loop.py) — heavily annotated; pairs with
[docs/LEARNING.md Lesson 1](../docs/LEARNING.md). Adapted from `moshi_mlx.local`
(Kyutai, Apache-2.0) with instrumentation and a headless benchmark mode added.

## Verification

`uv run duet-local --headless 100` must report p95 step time **< 80 ms** (the real-time
budget) and peak memory well under the machine's RAM. Current measured numbers live in
[docs/DECISIONS.md](../docs/DECISIONS.md) entry 0004.
