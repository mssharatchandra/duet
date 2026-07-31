# Duet Phase 2 — the hybrid SDR agent: Moshi mouth, Gemini brain.
#
# Architecture (the moshi-rag async-augmentation pattern):
#
#   80 ms audio loop (hard real-time)      async brain (seconds, never blocks)
#   ─────────────────────────────────      ────────────────────────────────────
#   mic → Mimi → gen.step → Mimi → spk     user audio → faster-whisper (ASR)
#              ▲                                     → Gemini Flash (persona)
#              └── on_text_hook ◄──── injector ◄──── talking point
#
# The ASR here is NOT a return to cascade-land: it feeds the *brain*, not the
# mouth. The audio loop never waits on it. If the whole right-hand column dies,
# the left keeps having a perfectly natural (if less substantive) conversation.
#
# Two modes:
#   --scripted  : no audio devices; a scripted lead "speaks" at set frames while
#                 Moshi runs on silence. Verifies the full brain→injection path
#                 end-to-end and measures each stage. Also what CI-adjacent
#                 local verification runs.
#   --live      : mic/speaker + real ASR. Wear headphones (no echo cancellation
#                 until the WebRTC transport lands in Phase 4).

import argparse
import multiprocessing
import os
import queue
import time

import huggingface_hub
import mlx.core as mx
import numpy as np
import rustymimi

from . import local_loop
from .asr_util import to_whisper_rate
from .env import load_repo_env
from .injector import TextInjector
from .persona import score_lead
from .reasoning import Guidance, ReasoningFailure, ReasoningLayer

FRAME_S = local_loop.FRAME_SIZE / local_loop.SAMPLE_RATE  # 0.08


def _make_hook(injector: TextInjector):
    """Bridge the pure-python injector to MLX: mutate the sampled token in place
    (same mechanism Kyutai's TTS uses — see docs/LEARNING.md Lesson 2)."""

    def on_text_hook(text_tokens: mx.array) -> None:
        sampled = int(text_tokens[0, 0].item())
        forced = injector.hook(sampled)
        if forced != sampled:
            text_tokens[:] = mx.array([[forced]], dtype=text_tokens.dtype)

    return on_text_hook


# --------------------------------------------------------------------------
# Scripted mode — the verifiable demo
# --------------------------------------------------------------------------

# (seconds_into_call, what the lead says). Objections straight from the playbook.
DEFAULT_SCRIPT = [
    (2.0, "Hi — yeah I run three coffee shops here in Austin, I'm the owner."),
    (10.0, "Honestly we already use spreadsheets for ordering and it works fine."),
    (18.0, "Hmm. And what does it cost?"),
    (26.0, "Okay, that's less than I expected. We'd want it before the fall rush."),
]


def run_scripted(args) -> None:
    print("[sdr] loading Moshi …")
    injector: TextInjector | None = None

    def hook(text_tokens):
        if injector is not None:
            _make_hook(injector)(text_tokens)

    gen, text_tokenizer, load_s = local_loop.load_model(args, on_text_hook=hook)
    injector = TextInjector(encode=lambda s: list(text_tokenizer.encode(s)), pace_pads=2)  # type: ignore
    brain = ReasoningLayer()
    print(f"[sdr] Moshi loaded in {load_s:.1f}s · brain model: {brain.model}")

    mimi_file = huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors")
    codec = rustymimi.StreamTokenizer(mimi_file)  # type: ignore

    silence = np.zeros(local_loop.FRAME_SIZE, np.float32)
    script = list(DEFAULT_SCRIPT)
    history: list[tuple[str, str]] = []
    monologue: list[tuple[float, str]] = []  # (t, word) — Moshi's speech as text
    events: list[str] = []
    pending_request_t: float | None = None
    last_signals: dict = {}
    total_frames = int(args.seconds / FRAME_S)

    for frame in range(total_frames):
        t = frame * FRAME_S

        # The scripted lead "speaks": in live mode this is ASR output; here we
        # hand the transcript to the brain directly and mark the user as loud
        # for the utterance duration so injection politeness rules apply.
        if script and t >= script[0][0]:
            _, utterance = script.pop(0)
            events.append(f"{t:6.2f}s  LEAD: {utterance}")
            brain.request(history, utterance)
            history.append(("lead", utterance))
            pending_request_t = t

        # Simulated user energy: loud for ~1.5 s after each scripted line.
        speaking = pending_request_t is not None and (t - pending_request_t) < 1.5
        injector.on_user_frame(0.1 if speaking else 0.0)

        # Poll the brain — non-blocking, once per frame, like the live loop.
        result = brain.poll()
        if isinstance(result, Guidance):
            last_signals = result.lead_signals
            events.append(
                f"{t:6.2f}s  BRAIN ({result.latency_ms:.0f} ms, intent={result.intent}"
                f"{', objection=' + result.objection_type if result.objection_type else ''}):"
                f" inject → “{result.talking_point}”"
            )
            injector.inject(result.talking_point)
            history.append(("agent", result.talking_point))
        elif isinstance(result, ReasoningFailure):
            events.append(f"{t:6.2f}s  BRAIN FAILED ({result.reason}) — Moshi continues unaided")

        # The unchanged 80 ms heartbeat.
        codec.encode(silence)
        deadline = time.time() + 5.0
        while (data := codec.get_encoded()) is None:
            if time.time() > deadline:
                raise RuntimeError("Mimi encoder stalled")
            time.sleep(0.001)
        audio_out, piece = local_loop.step_once(gen, text_tokenizer, data)
        if piece is not None:
            monologue.append((t, piece))
        if audio_out is not None:
            codec.decode(audio_out)

    # ---- report ----
    print(f"\n===== scripted call transcript ({args.seconds:.0f}s simulated) =====")
    for line in events:
        print(line)
    spoken = "".join(p for _, p in monologue)
    print(f"\nMOSHI actually said (inner monologue): {spoken.strip()!r}")
    score = score_lead(last_signals)
    print(f"\nLEAD SCORE: {score.total}/100 → {score.verdict}  breakdown={score.breakdown}  signals={last_signals}")
    print(
        f"injections: {injector.injected} completed · {injector.cancelled_by_barge_in} cancelled by barge-in"
        f" · {injector.dropped_stale} dropped stale"
    )
    lat = brain.stats.latencies_ms
    print(
        f"brain: {brain.stats.calls} calls · {brain.stats.failures} failures"
        f" · latency avg {np.mean(lat):.0f} ms" if lat else "brain: no successful calls"
    )
    print(
        f"brain tokens: {brain.stats.tokens_in} in / {brain.stats.tokens_out} out"
        f" ≈ ${brain.stats.cost_usd(brain.model):.5f} at list price (free tier during dev)"
    )
    # verification: every scripted line should have produced a completed injection
    expected = len(DEFAULT_SCRIPT)
    if injector.injected >= expected - 1 and brain.stats.failures == 0:
        print("VERDICT: PASS — brain guidance was injected into Moshi's speech")
    else:
        print(f"VERDICT: FAIL — expected ≥{expected - 1} injections, got {injector.injected}")
        raise SystemExit(1)


# --------------------------------------------------------------------------
# Live mode — 3 processes: audio (reused), model (+hook), brain (ASR+Gemini)
# --------------------------------------------------------------------------


def model_process(to_model, from_model, pcm_tap, inject_q, args):
    injector: TextInjector | None = None

    def hook(text_tokens):
        if injector is not None:
            _make_hook(injector)(text_tokens)

    gen, text_tokenizer, load_s = local_loop.load_model(args, on_text_hook=hook)
    injector = TextInjector(encode=lambda s: list(text_tokenizer.encode(s)))  # type: ignore
    print(f"[model] loaded in {load_s:.1f}s — live SDR call, Ctrl-C to stop")
    from_model.put("ready")
    try:
        while True:
            user_frame, user_rms = to_model.get()
            injector.on_user_frame(user_rms)
            try:
                injector.inject(inject_q.get_nowait())
            except queue.Empty:
                pass
            audio_out, piece = local_loop.step_once(gen, text_tokenizer, user_frame)
            if piece is not None:
                print(piece, end="", flush=True)
                pcm_tap.put_nowait(("agent_text", piece))
            if audio_out is not None:
                from_model.put_nowait(audio_out)
    except KeyboardInterrupt:
        pass
    finally:
        print(
            f"\n[injector] {injector.injected} injected · {injector.cancelled_by_barge_in} barge-in cancels"
            f" · {injector.dropped_stale} stale drops"
        )


def brain_process(pcm_tap, inject_q, args):
    """Rolling ASR on the user's audio + Gemini persona calls. Fully off the hot path."""
    load_repo_env()
    from faster_whisper import WhisperModel  # optional dep: uv pip install -e '.[live]'

    asr = WhisperModel(os.environ.get("ASR_MODEL", "small.en"), device="cpu", compute_type="int8")
    brain = ReasoningLayer()
    history: list[tuple[str, str]] = []
    buf: list[np.ndarray] = []
    voiced_frames = 0
    quiet_frames = 0
    try:
        while True:
            kind, payload = pcm_tap.get()
            if kind == "agent_text":
                if history and history[-1][0] == "agent":
                    history[-1] = ("agent", history[-1][1] + payload)
                else:
                    history.append(("agent", payload))
                continue
            pcm = payload
            rms = float(np.sqrt(np.mean(pcm**2)))
            if rms > 0.02:
                voiced_frames += 1
                quiet_frames = 0
                buf.append(pcm)
            elif buf:
                quiet_frames += 1
                buf.append(pcm)
                # utterance boundary: ≥0.6 s silence after ≥0.4 s of speech
                if quiet_frames >= 8 and voiced_frames >= 5:
                    audio = np.concatenate(buf)
                    buf, voiced_frames, quiet_frames = [], 0, 0
                    segments, _ = asr.transcribe(to_whisper_rate(audio), language="en", beam_size=1)
                    text = " ".join(s.text.strip() for s in segments).strip()
                    if text:
                        history.append(("lead", text))
                        brain.request(history[:-1], text)
            result = brain.poll()
            if isinstance(result, Guidance):
                inject_q.put_nowait(result.talking_point)
                history.append(("agent", result.talking_point))
    except KeyboardInterrupt:
        pass
    finally:
        print(
            f"\n[brain] {brain.stats.calls} calls · {brain.stats.failures} failures ·"
            f" ${brain.stats.cost_usd(brain.model):.5f} est"
        )


def audio_process(to_model, from_model, pcm_tap, args):
    """Same plumbing as local_loop.audio_process, plus: each mic frame is also
    tee'd (with its RMS) to the brain, and RMS rides along to the model for the
    injector's politeness rules."""
    import asyncio

    import sounddevice as sd

    mimi_file = huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors")
    mic_q: queue.Queue = queue.Queue()
    spk_q: queue.Queue = queue.Queue()
    rms_q: queue.Queue = queue.Queue()
    codec = rustymimi.StreamTokenizer(mimi_file)  # type: ignore
    assert from_model.get() == "ready"

    for i in range(4):
        codec.encode(np.zeros(local_loop.FRAME_SIZE, np.float32))
        while (data := codec.get_encoded()) is None:
            time.sleep(0.01)
        to_model.put_nowait((data, 0.0))
        if i > 0:
            from_model.get()

    async def relay():
        while True:
            moved = False
            try:
                pcm = mic_q.get(block=False)
                rms = float(np.sqrt(np.mean(pcm**2)))
                rms_q.put_nowait(rms)
                pcm_tap.put_nowait(("pcm", pcm))
                codec.encode(pcm)
                moved = True
            except queue.Empty:
                pass
            if (data := codec.get_encoded()) is not None:
                to_model.put_nowait((data, rms_q.get_nowait() if not rms_q.empty() else 0.0))
                moved = True
            try:
                codec.decode(from_model.get(block=False))
                moved = True
            except queue.Empty:
                pass
            if (data := codec.get_decoded()) is not None:
                spk_q.put_nowait(data)
                moved = True
            if not moved:
                await asyncio.sleep(0.001)

    def on_mic(in_data, frames, _t, _s):
        mic_q.put_nowait(in_data[:, 0].astype(np.float32).copy())

    def on_speaker(out_data, frames, _t, _s):
        try:
            out_data[:, 0] = spk_q.get(block=False)
        except queue.Empty:
            out_data.fill(0)

    mic = sd.InputStream(samplerate=local_loop.SAMPLE_RATE, channels=1, blocksize=local_loop.FRAME_SIZE, callback=on_mic)
    spk = sd.OutputStream(samplerate=local_loop.SAMPLE_RATE, channels=1, blocksize=local_loop.FRAME_SIZE, callback=on_speaker)

    try:
        with mic, spk:
            asyncio.run(relay())
    except KeyboardInterrupt:
        pass


def run_live(args) -> None:
    to_model: multiprocessing.Queue = multiprocessing.Queue()
    from_model: multiprocessing.Queue = multiprocessing.Queue()
    pcm_tap: multiprocessing.Queue = multiprocessing.Queue()
    inject_q: multiprocessing.Queue = multiprocessing.Queue()
    procs = [
        multiprocessing.Process(target=model_process, args=(to_model, from_model, pcm_tap, inject_q, args)),
        multiprocessing.Process(target=audio_process, args=(to_model, from_model, pcm_tap, args)),
        multiprocessing.Process(target=brain_process, args=(pcm_tap, inject_q, args)),
    ]
    for p in procs:
        p.start()
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


def main() -> None:
    load_repo_env()
    parser = argparse.ArgumentParser(description="Duet Phase 2: hybrid SDR agent (Moshi mouth + Gemini brain)")
    parser.add_argument("--live", action="store_true", help="mic/speaker call (wear headphones)")
    parser.add_argument("--seconds", type=float, default=34.0, help="scripted-mode call length")
    parser.add_argument("-q", "--quantized", type=int, choices=[4, 8], default=4)
    parser.add_argument("--hf-repo", type=str, default=None)
    parser.add_argument("--steps", type=int, default=4000)
    args = parser.parse_args()
    if args.hf_repo is None:
        args.hf_repo = local_loop.DEFAULT_REPOS[args.quantized]

    if args.live:
        run_live(args)
    else:
        run_scripted(args)


if __name__ == "__main__":
    main()
