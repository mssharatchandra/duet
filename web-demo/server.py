#!/usr/bin/env python3
# Duet web demo — talk to the hybrid SDR agent from a browser instead of a terminal.
#
# Why a browser: getUserMedia gives echo cancellation + noise suppression for
# free (the terminal demo's raw audio path has neither — speakers made Moshi
# hear itself), and the page shows everything that used to be invisible:
# your live transcript (faster-whisper), Duet's words as it speaks them
# (the inner monologue), brain injections, and audio levels.
#
# Transport: one WebSocket. Binary frames = 1920-sample float32 PCM @ 24 kHz
# (one 80 ms Mimi frame) in each direction. Text frames = JSON events.
# The browser's AudioContext runs at 24 kHz so no resampling happens anywhere.
#
# Run:  agent/.venv/bin/python web-demo/server.py   →  http://localhost:8990

import argparse
import asyncio
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from duet_agent import local_loop  # noqa: E402
from duet_agent.env import load_repo_env  # noqa: E402
from duet_agent.injector import TextInjector  # noqa: E402
from duet_agent.reasoning import Guidance, ReasoningFailure, ReasoningLayer  # noqa: E402

FRAME = local_loop.FRAME_SIZE
STATIC = Path(__file__).parent / "static"


class Session:
    """One live conversation: model thread (hard real-time) + brain thread (ASR + Gemini)."""

    def __init__(self, args):
        self.args = args
        self.mic_q: queue.Queue = queue.Queue(maxsize=64)    # browser → model
        self.spk_q: queue.Queue = queue.Queue(maxsize=64)    # model → browser
        self.events: queue.Queue = queue.Queue()             # JSON events → browser
        self.tap_q: queue.Queue = queue.Queue(maxsize=256)   # mic pcm copy → brain
        self.running = True
        self.injector: TextInjector | None = None
        self.step_ms: list[float] = []

    def emit(self, **ev) -> None:
        self.events.put(ev)

    def start(self) -> None:
        threading.Thread(target=self._model_loop, daemon=True).start()
        threading.Thread(target=self._brain_loop, daemon=True).start()

    def stop(self) -> None:
        self.running = False

    # -- the 80 ms heartbeat ------------------------------------------------

    def _model_loop(self) -> None:
        import huggingface_hub
        import mlx.core as mx
        import rustymimi

        def hook(text_tokens):
            if self.injector is not None:
                sampled = int(text_tokens[0, 0].item())
                forced = self.injector.hook(sampled)
                if forced != sampled:
                    text_tokens[:] = mx.array([[forced]], dtype=text_tokens.dtype)

        self.emit(type="status", text=f"loading Moshi ({self.args.hf_repo}) …")
        try:
            gen, tok, load_s = local_loop.load_model(self.args, on_text_hook=hook)
            self.injector = TextInjector(encode=lambda s: list(tok.encode(s)))  # type: ignore
            codec = rustymimi.StreamTokenizer(
                huggingface_hub.hf_hub_download(self.args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors"))  # type: ignore
        except Exception as e:
            self.emit(type="error", text=f"model failed to load: {e}")
            return
        self.emit(type="status", text=f"ready — Moshi loaded in {load_s:.1f}s. Say hi!", ready=True)

        last_stats = time.time()
        dropped = 0
        while self.running:
            try:
                pcm = self.mic_q.get(timeout=0.5)
            except queue.Empty:
                continue
            # Stay live: if the model fell behind and mic frames piled up,
            # skip ahead rather than drifting seconds out of sync.
            while self.mic_q.qsize() > 5:
                pcm = self.mic_q.get_nowait()
                dropped += 1
                if dropped % 25 == 0:
                    self.emit(type="status", text=f"⚠ model behind real-time — dropped {dropped} frames (close heavy apps?)")
            rms = float(np.sqrt(np.mean(pcm**2)))
            self.injector.on_user_frame(rms)
            try:
                self.tap_q.put_nowait(pcm)
            except queue.Full:
                pass

            t0 = time.perf_counter()
            codec.encode(pcm)
            deadline = time.time() + 30
            while (data := codec.get_encoded()) is None:
                if time.time() > deadline or not self.running:
                    return
                time.sleep(0.001)
            audio_out, piece = local_loop.step_once(gen, tok, data)
            self.step_ms.append((time.perf_counter() - t0) * 1e3)
            if piece is not None:
                self.emit(type="duet", text=piece)
            if audio_out is not None:
                codec.decode(audio_out)
                got = codec.get_decoded()
                for _ in range(200):
                    if got is not None:
                        break
                    time.sleep(0.001)
                    got = codec.get_decoded()
                if got is not None:
                    try:
                        self.spk_q.put_nowait(np.asarray(got, np.float32)[:FRAME])
                    except queue.Full:
                        pass
            if time.time() - last_stats > 2 and self.step_ms:
                arr = np.array(self.step_ms[-100:])
                self.emit(type="stats", p50=round(float(np.percentile(arr, 50)), 1),
                          p95=round(float(np.percentile(arr, 95)), 1), frames=len(self.step_ms))
                last_stats = time.time()

    # -- the slow brain -------------------------------------------------------

    def _brain_loop(self) -> None:
        try:
            from faster_whisper import WhisperModel
            asr = WhisperModel("base.en", device="cpu", compute_type="int8")
        except Exception as e:
            self.emit(type="status", text=f"ASR unavailable ({e}) — transcript disabled, Moshi still works")
            asr = None
        try:
            brain = ReasoningLayer()
        except RuntimeError as e:
            self.emit(type="status", text=f"brain disabled: {e}")
            brain = None

        history: list[tuple[str, str]] = []
        buf: list[np.ndarray] = []
        voiced = quiet = 0
        while self.running:
            try:
                pcm = self.tap_q.get(timeout=0.5)
            except queue.Empty:
                pcm = None
            if pcm is not None and asr is not None:
                rms = float(np.sqrt(np.mean(pcm**2)))
                if rms > 0.015:
                    voiced += 1
                    quiet = 0
                    buf.append(pcm)
                elif buf:
                    quiet += 1
                    buf.append(pcm)
                    if quiet >= 8 and voiced >= 4:  # ≥0.3 s speech then 0.6 s silence
                        audio = np.concatenate(buf)
                        buf, voiced, quiet = [], 0, 0
                        segments, _ = asr.transcribe(audio, language="en", beam_size=1)
                        text = " ".join(s.text.strip() for s in segments).strip()
                        if text:
                            self.emit(type="you", text=text)
                            if brain:
                                brain.request(history, text)
                            history.append(("lead", text))
                    elif quiet >= 8:
                        buf, voiced, quiet = [], 0, 0
            if brain:
                result = brain.poll()
                if isinstance(result, Guidance) and self.injector:
                    self.injector.inject(result.talking_point)
                    history.append(("agent", result.talking_point))
                    self.emit(type="brain", text=result.talking_point,
                              latency_ms=round(result.latency_ms), intent=result.intent)
                elif isinstance(result, ReasoningFailure):
                    self.emit(type="status", text=f"brain call failed ({result.reason[:60]}) — continuing unaided")


active: dict = {"session": None}


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(max_msg_size=1 << 20)
    await ws.prepare(request)
    if active["session"] is not None:
        await ws.send_json({"type": "error", "text": "another session is active — one caller at a time"})
        await ws.close()
        return ws

    session = Session(request.app["args"])
    active["session"] = session
    session.start()

    async def pump() -> None:
        while session.running:
            sent = False
            try:
                await ws.send_bytes(session.spk_q.get_nowait().tobytes())
                sent = True
            except queue.Empty:
                pass
            try:
                await ws.send_json(session.events.get_nowait())
                sent = True
            except queue.Empty:
                pass
            if not sent:
                await asyncio.sleep(0.01)

    pump_task = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY and len(msg.data) == FRAME * 4:
                try:
                    session.mic_q.put_nowait(np.frombuffer(msg.data, np.float32).copy())
                except queue.Full:
                    pass
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        session.stop()
        pump_task.cancel()
        active["session"] = None
    return ws


def main() -> None:
    load_repo_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--quantized", type=int, choices=[4, 8], default=8,
                    help="8-bit default: audibly cleaner voice, still real-time on M-series")
    ap.add_argument("--hf-repo", default=None)
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--port", type=int, default=8990)
    args = ap.parse_args()
    if args.hf_repo is None:
        args.hf_repo = local_loop.DEFAULT_REPOS[args.quantized]

    app = web.Application()
    app["args"] = args
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/", lambda r: web.FileResponse(STATIC / "index.html"))
    app.router.add_static("/static", STATIC)
    print(f"Duet web demo → http://localhost:{args.port}  (model: {args.hf_repo})")
    web.run_app(app, port=args.port, print=None)


if __name__ == "__main__":
    main()
