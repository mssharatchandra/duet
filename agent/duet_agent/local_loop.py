# Duet Phase 1 — the minimal full-duplex loop (Mac-local, zero cloud).
#
# Adapted from `moshi_mlx.local` (Copyright (c) Kyutai — Apache-2.0), with
# simplifications, latency/memory instrumentation, and a --headless benchmark
# mode. Read this file top to bottom alongside docs/LEARNING.md Lesson 1.
#
# THE ONE IDEA THAT MAKES THIS FULL-DUPLEX
# ----------------------------------------
# There is no turn-taking logic in this file. No VAD, no "user finished
# speaking" detector, no interrupt handler. Instead, time is sliced into
# 80 ms frames, and EVERY frame does the same two things simultaneously:
#
#   1. the user's last 80 ms of mic audio is encoded to 8 Mimi codec tokens
#      and fed INTO the model  (the model is always listening), and
#   2. the model emits 8 Mimi tokens of ITS OWN next 80 ms of speech
#      (the model is always speaking — "silence" is just tokens that
#      decode to near-zero audio).
#
# Interruption handling, backchannels ("mm-hm"), and yielding the floor are
# not code — they are behavior the model learned from real overlapping
# conversations. When you barge in mid-sentence, your audio tokens change
# the model's context, and the most probable continuation of ITS OWN audio
# stream becomes "stop talking / acknowledge". That's the entire mechanism.

import argparse
import asyncio
import multiprocessing
import queue
import resource
import time

import huggingface_hub
import mlx.core as mx
import mlx.nn as nn
import numpy as np
import rustymimi
import sentencepiece
import sounddevice as sd
from moshi_mlx import models, utils

SAMPLE_RATE = 24_000
FRAME_SIZE = 1_920  # 1920 samples / 24 kHz = 80 ms — Mimi's frame; the tick of the whole system
MIMI_CODEBOOKS = 8  # tokens per frame per direction (audio is 8 parallel token streams)
TEXT_PAD_TOKENS = (0, 3)  # emitted on frames where the model has no word to "think"

DEFAULT_REPOS = {4: "kyutai/moshiko-mlx-q4", 8: "kyutai/moshiko-mlx-q8", None: "kyutai/moshiko-mlx-bf16"}


def _report_footprint(label: str) -> None:
    rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9  # bytes on macOS
    try:
        metal_gb = mx.get_peak_memory() / 1e9
    except AttributeError:
        metal_gb = mx.metal.get_peak_memory() / 1e9
    print(f"\n[{label}] peak RSS {rss_gb:.2f} GB · peak Metal (GPU) memory {metal_gb:.2f} GB")


def _report_steps(step_ms: list[float]) -> None:
    if not step_ms:
        return
    arr = np.array(step_ms)
    print(
        f"[model] steps: {len(arr)} · avg {arr.mean():.1f} ms · p50 {np.percentile(arr, 50):.1f} ms"
        f" · p95 {np.percentile(arr, 95):.1f} ms · max {arr.max():.1f} ms"
    )
    # The first few steps pay one-off costs (Metal kernel compilation, cache
    # allocation). Real-time viability is judged on steady state.
    if len(arr) > 20:
        steady = arr[10:]
        p95 = np.percentile(steady, 95)
        verdict = "REAL-TIME OK" if p95 < 80 else "OVER BUDGET"
        print(
            f"[model] steady state (steps 11+): p50 {np.percentile(steady, 50):.1f} ms"
            f" · p95 {p95:.1f} ms · max {steady.max():.1f} ms"
            f" · 80 ms budget → {verdict} ({80 - p95:+.1f} ms headroom at p95)"
        )


def load_model(args) -> tuple[models.LmGen, "sentencepiece.SentencePieceProcessor", float]:
    """Load the Moshi language model (the 'brain+mouth'), quantized, onto the GPU."""
    weight_names = {4: "model.q4.safetensors", 8: "model.q8.safetensors", None: "model.safetensors"}
    model_file = huggingface_hub.hf_hub_download(args.hf_repo, weight_names[args.quantized])
    tokenizer_file = huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer_spm_32k_3.model")

    t0 = time.perf_counter()
    text_tokenizer = sentencepiece.SentencePieceProcessor(tokenizer_file)  # type: ignore
    mx.random.seed(299792458)  # determinism-friendly default; sampling still has temperature
    model = models.Lm(models.config_v0_1())
    model.set_dtype(mx.bfloat16)
    if args.quantized is not None:
        # group_size must match how the checkpoint was quantized upstream
        nn.quantize(model, bits=args.quantized, group_size=32 if args.quantized == 4 else 64)
    model.load_weights(model_file, strict=True)
    model.warmup()  # first MLX call compiles Metal kernels; do it before real-time starts
    load_s = time.perf_counter() - t0

    gen = models.LmGen(
        model=model,
        max_steps=args.steps + 5,  # KV-cache length: 4000 frames × 80 ms ≈ 5.3 min max session
        text_sampler=utils.Sampler(),
        audio_sampler=utils.Sampler(),
        check=False,
    )
    return gen, text_tokenizer, load_s


def step_once(gen, text_tokenizer, user_frame) -> tuple[np.ndarray | None, str | None]:
    """One 80 ms tick of the conversation. This function IS the full-duplex core.

    In: one frame of the USER's audio as Mimi tokens (shape → (1, 8)).
    Out: one frame of MOSHI's next audio as Mimi tokens, plus optionally a word
    of Moshi's 'inner monologue' — the text stream it thinks in while speaking.
    """
    codes = mx.array(user_frame).transpose(1, 0)[:, :MIMI_CODEBOOKS]  # user audio INTO the model
    text_token = gen.step(codes)  # ...and the model's own next frame OUT, same call
    text_token = text_token[0].item()
    audio_tokens = gen.last_audio_tokens()

    piece = None
    if text_token not in TEXT_PAD_TOKENS:
        piece = text_tokenizer.id_to_piece(text_token).replace("▁", " ")  # type: ignore
    out = np.array(audio_tokens).astype(np.uint32) if audio_tokens is not None else None
    return out, piece


# ---------------------------------------------------------------------------
# Live mode: two processes, because both sides have a hard real-time budget.
# The MODEL process must finish each step in <80 ms; the AUDIO process must
# never let the sound card starve. Python's GIL makes sharing one process
# risky, so they talk over two queues — exactly one frame of tokens at a time.
# ---------------------------------------------------------------------------


def model_process(to_model: multiprocessing.Queue, from_model: multiprocessing.Queue, args) -> None:
    gen, text_tokenizer, load_s = load_model(args)
    print(f"[model] loaded + warmed up in {load_s:.1f}s — say hello, and try interrupting it mid-sentence")
    from_model.put("ready")

    step_ms: list[float] = []
    try:
        while True:
            user_frame = to_model.get()  # blocks until the next 80 ms of user audio arrives
            t0 = time.perf_counter()
            audio_out, piece = step_once(gen, text_tokenizer, user_frame)
            step_ms.append((time.perf_counter() - t0) * 1e3)
            if piece is not None:
                print(piece, end="", flush=True)  # Moshi's inner monologue, word by word
            if audio_out is not None:
                from_model.put_nowait(audio_out)
    except KeyboardInterrupt:
        pass
    finally:
        _report_steps(step_ms)
        _report_footprint("model")


def audio_process(to_model: multiprocessing.Queue, from_model: multiprocessing.Queue, args) -> None:
    """Owns the mic, the speaker, and the Mimi codec (Rust, runs its own threads).

    Four tiny relay loops shuttle frames along the pipeline:
      mic callback → encode → to_model → (model) → from_model → decode → speaker callback
    """
    mimi_file = huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors")
    mic_q: queue.Queue = queue.Queue()
    spk_q: queue.Queue = queue.Queue()
    codec = rustymimi.StreamTokenizer(mimi_file)  # type: ignore

    assert from_model.get() == "ready"

    # Warm the codec + model pipeline with a few frames of silence so kernel
    # compilation doesn't cause an audible stall on the first real frame.
    for i in range(4):
        codec.encode(np.zeros(FRAME_SIZE, np.float32))
        while (data := codec.get_encoded()) is None:
            time.sleep(0.01)
        to_model.put_nowait(data)
        if i > 0:
            codec.decode(from_model.get())
            while codec.get_decoded() is None:
                time.sleep(0.01)

    async def mic_to_codec():  # user PCM → Mimi encoder
        while True:
            try:
                codec.encode(mic_q.get(block=False))
            except queue.Empty:
                await asyncio.sleep(0.001)

    async def codec_to_model():  # encoded user tokens → model process
        while True:
            if (data := codec.get_encoded()) is None:
                await asyncio.sleep(0.001)
                continue
            to_model.put_nowait(data)

    async def model_to_codec():  # Moshi's audio tokens → Mimi decoder
        while True:
            try:
                codec.decode(from_model.get(block=False))
            except queue.Empty:
                await asyncio.sleep(0.001)

    async def codec_to_speaker():  # decoded Moshi PCM → speaker queue
        while True:
            if (data := codec.get_decoded()) is None:
                await asyncio.sleep(0.001)
                continue
            spk_q.put_nowait(data)

    def on_mic(in_data, frames, _time, _status):
        # NOTE: the mic NEVER stops feeding the model — not even while Moshi is
        # talking. Half-duplex systems mute or gate this path; we must not.
        mic_q.put_nowait(in_data[:, 0].astype(np.float32).copy())

    lag_count = 0

    def on_speaker(out_data, frames, _time, _status):
        nonlocal lag_count
        try:
            out_data[:, 0] = spk_q.get(block=False)
        except queue.Empty:
            # Model missed the 80 ms budget → emit silence rather than glitch.
            lag_count += 1
            out_data.fill(0)

    mic = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=FRAME_SIZE, callback=on_mic)
    spk = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=FRAME_SIZE, callback=on_speaker)

    async def run():
        with mic, spk:
            await asyncio.gather(mic_to_codec(), codec_to_model(), model_to_codec(), codec_to_speaker())

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        if lag_count:
            print(f"\n[audio] speaker starved on {lag_count} frames (model exceeded 80 ms budget)")


# ---------------------------------------------------------------------------
# Headless mode: same model, same codec, no sound card. Feeds silence frames
# and measures whether each step fits the 80 ms real-time budget. This is how
# we verify performance and memory footprint on a machine without touching a
# mic — and later, it's the seed of the Phase 3 benchmark harness.
# ---------------------------------------------------------------------------


def run_headless(args) -> None:
    print(f"[headless] loading {args.hf_repo} …")
    gen, text_tokenizer, load_s = load_model(args)
    print(f"[headless] model loaded + warmed up in {load_s:.1f}s")
    mimi_file = huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors")
    codec = rustymimi.StreamTokenizer(mimi_file)  # type: ignore

    step_ms: list[float] = []
    words: list[str] = []
    silence = np.zeros(FRAME_SIZE, np.float32)
    for i in range(args.headless):
        codec.encode(silence)
        deadline = time.time() + 5.0
        while (data := codec.get_encoded()) is None:
            if time.time() > deadline:
                raise RuntimeError("Mimi encoder stalled")
            time.sleep(0.001)
        t0 = time.perf_counter()
        audio_out, piece = step_once(gen, text_tokenizer, data)
        step_ms.append((time.perf_counter() - t0) * 1e3)
        if piece is not None:
            words.append(piece)
        if audio_out is not None:
            codec.decode(audio_out)  # exercise the decode path too, like live mode

    # Drain the codec's Rust worker threads before exit so they don't complain
    # about the channel closing mid-frame.
    deadline = time.time() + 1.0
    while codec.get_decoded() is not None or time.time() < deadline:
        if time.time() > deadline:
            break
        time.sleep(0.01)

    print(f"[headless] ran {args.headless} frames = {args.headless * 0.08:.1f} s of simulated conversation")
    if words:
        print(f"[headless] inner monologue during silence: {''.join(words)!r}")
    _report_steps(step_ms)
    _report_footprint("headless")


def main() -> None:
    parser = argparse.ArgumentParser(description="Duet Phase 1: local full-duplex loop (Moshi on MLX)")
    parser.add_argument("-q", "--quantized", type=int, choices=[4, 8], default=4,
                        help="weight quantization; 4 fits comfortably in 16 GB unified memory")
    parser.add_argument("--bf16", action="store_true", help="full-precision weights (needs ~16 GB free)")
    parser.add_argument("--hf-repo", type=str, default=None)
    parser.add_argument("--steps", type=int, default=4000, help="max frames per session (4000 ≈ 5.3 min)")
    parser.add_argument("--headless", type=int, default=0, metavar="N",
                        help="benchmark N frames with silent input instead of running mic/speaker")
    args = parser.parse_args()
    if args.bf16:
        args.quantized = None
    if args.hf_repo is None:
        args.hf_repo = DEFAULT_REPOS[args.quantized]

    if args.headless:
        run_headless(args)
        return

    to_model: multiprocessing.Queue = multiprocessing.Queue()
    from_model: multiprocessing.Queue = multiprocessing.Queue()
    procs = [
        multiprocessing.Process(target=model_process, args=(to_model, from_model, args)),
        multiprocessing.Process(target=audio_process, args=(to_model, from_model, args)),
    ]
    for p in procs:
        p.start()
    print("[duet] starting — Ctrl-C to stop")
    try:
        while all(p.is_alive() for p in procs):
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[duet] stopping…")
    finally:
        for p in procs:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()


if __name__ == "__main__":
    main()
