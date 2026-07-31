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
# (one 80 ms Mimi frame) in each direction. Text frames = JSON control/events
# in both directions — see `ctrl.get("type") == "control"` below for the one
# the browser sends (the "record this session" toggle).
# The browser's AudioContext runs at 24 kHz so no resampling happens anywhere.
#
# Run:  agent/.venv/bin/python web-demo/server.py   →  http://localhost:8990
# Run without loading Moshi (ASR/brain/capture only, e.g. to test --capture
# without a GPU or while another process is using the model):
#       agent/.venv/bin/python web-demo/server.py --no-model --capture

import argparse
import asyncio
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from duet_agent.asr_util import to_whisper_rate  # noqa: E402
from duet_agent.env import load_repo_env  # noqa: E402
from duet_agent.injector import TextInjector  # noqa: E402
from duet_agent.reasoning import Guidance, ReasoningFailure, ReasoningLayer  # noqa: E402

from capture import SessionCapture  # noqa: E402  — pure module, see capture.py header; safe under --no-model

# NOTE: `duet_agent.local_loop` (and therefore mlx / moshi_mlx / rustymimi) is deliberately NOT
# imported at module scope. It's imported lazily, only on the path that actually loads Moshi
# (Session._model_loop's real branch, and main()'s hf-repo default resolution) so that
# `--no-model` starts this server without ever touching the model stack — required so the
# capture feature can be built/tested while another process may be using the GPU (DECISIONS 0008).
FRAME = 1_920  # duplicated from local_loop.FRAME_SIZE — see the import note above for why
STATIC = Path(__file__).parent / "static"
SESSIONS_DIR = Path(__file__).resolve().parents[1] / "eval" / "asr" / "sessions"
CAPTURES: dict[str, SessionCapture] = {}  # session_id -> capture, kept for the process lifetime so
                                           # /corrections can still land after the WS disconnects


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
        # session capture — opt-in only; see enable_capture(). session_id doubles as the
        # eval/asr/sessions/<session_id>/ directory name once capture is turned on.
        self.session_id = f"{int(time.time())}-{os.urandom(3).hex()}"
        self.capture: SessionCapture | None = None
        if getattr(args, "capture", False):
            self.enable_capture()

    def emit(self, **ev) -> None:
        self.events.put(ev)

    def enable_capture(self) -> None:
        """Turn on session recording. Idempotent — a second call (e.g. CLI --capture plus a
        redundant UI toggle) is a no-op, not a second directory."""
        if self.capture is not None:
            return
        self.capture = SessionCapture(SESSIONS_DIR / self.session_id)
        CAPTURES[self.session_id] = self.capture
        self.emit(type="capture_status", enabled=True, session_id=self.session_id)

    def start(self) -> None:
        threading.Thread(target=self._model_loop, daemon=True).start()
        threading.Thread(target=self._brain_loop, daemon=True).start()

    def stop(self) -> None:
        self.running = False

    # -- the 80 ms heartbeat ------------------------------------------------

    def _model_loop(self) -> None:
        if self.args.no_model:
            self._model_loop_stub()
            return

        import huggingface_hub
        import mlx.core as mx
        import rustymimi
        from duet_agent import local_loop

        def hook(text_tokens):
            if self.injector is not None:
                sampled = int(text_tokens[0, 0].item())
                forced = self.injector.hook(sampled)
                if forced != sampled:
                    text_tokens[:] = mx.array([[forced]], dtype=text_tokens.dtype)

        self.emit(type="status", text=f"loading Moshi ({self.args.hf_repo}) …")
        try:
            gen, tok, load_s = local_loop.load_model(self.args, on_text_hook=hook)
            self.injector = TextInjector(encode=lambda s: list(tok.encode(s)), pace_pads=2)  # type: ignore
            codec = rustymimi.StreamTokenizer(
                huggingface_hub.hf_hub_download(self.args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors"))  # type: ignore
        except Exception as e:
            self.emit(type="error", text=f"model failed to load: {e}")
            return
        self.emit(type="status", text=f"ready — Moshi loaded in {load_s:.1f}s. Say hi!", ready=True)

        # One-frame pipeline: while the Rust codec encodes THIS frame on its own
        # threads, the model steps on the PREVIOUS frame's tokens, and decoded
        # output is drained opportunistically. Serializing these (encode-wait →
        # step → decode-wait) measured 92 ms/frame — over the 80 ms budget that
        # each stage individually meets with room to spare. Costs one frame
        # (80 ms) of added response latency; buys back ~40 ms of budget per tick.
        last_stats = time.time()
        dropped = 0
        pending_tokens = None
        while self.running:
            while True:  # drain decoded agent audio (never block on it)
                got = codec.get_decoded()
                if got is None:
                    break
                try:
                    self.spk_q.put_nowait(np.asarray(got, np.float32)[:FRAME])
                except queue.Full:
                    pass

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

            codec.encode(pcm)  # submit; Rust encodes while we step below
            if pending_tokens is not None:
                t0 = time.perf_counter()
                audio_out, piece = local_loop.step_once(gen, tok, pending_tokens)
                self.step_ms.append((time.perf_counter() - t0) * 1e3)
                if piece is not None:
                    self.emit(type="duet", text=piece)
                if audio_out is not None:
                    codec.decode(audio_out)  # submit only; drained at loop top

            deadline = time.time() + 30
            while (pending_tokens := codec.get_encoded()) is None:
                if time.time() > deadline or not self.running:
                    return
                time.sleep(0.001)

            if time.time() - last_stats > 2 and self.step_ms:
                arr = np.array(self.step_ms[-100:])
                self.emit(type="stats", p50=round(float(np.percentile(arr, 50)), 1),
                          p95=round(float(np.percentile(arr, 95)), 1), frames=len(self.step_ms))
                last_stats = time.time()

    def _model_loop_stub(self) -> None:
        """--no-model path: no mlx/moshi_mlx/rustymimi import, no weights, no GPU memory —
        required so --capture can be developed/tested without a model load while another
        process may be using the GPU (docs/DECISIONS.md 0008 on resource contention). Mic
        frames still flow to the brain thread via tap_q; there's just no mouth to speak back,
        so the speaker stays silent and no `duet`/`stats` events are ever emitted."""
        self.emit(type="status", text="--no-model: Moshi skipped — ASR/brain/capture only", ready=True)
        while self.running:
            try:
                pcm = self.mic_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.tap_q.put_nowait(pcm)
            except queue.Full:
                pass

    # -- the slow brain -------------------------------------------------------

    def _brain_loop(self) -> None:
        try:
            from faster_whisper import WhisperModel
            asr = WhisperModel(os.environ.get("ASR_MODEL", "small.en"), device="cpu", compute_type="int8")
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
            # Feed capture the SAME frame, in the SAME order, as the inline segmenter below —
            # both run identical thresholds (SessionCapture mirrors these on purpose, see
            # capture.py's header), so they close an utterance on the exact same frame. That's
            # what lets `cap_record` below be the capture-side record for whatever text the ASR
            # branch produces this iteration, with no separate alignment bookkeeping needed.
            cap_record = self.capture.add_frame(pcm) if (pcm is not None and self.capture is not None) else None
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
                        segments, _ = asr.transcribe(to_whisper_rate(audio), language="en", beam_size=1)
                        text = " ".join(s.text.strip() for s in segments).strip()
                        if text:
                            self.emit(type="you", text=text)
                            if self.capture is not None and cap_record is not None:
                                self.capture.set_hypothesis(cap_record.utterance_id, text)
                                self.emit(type="captured", utterance_id=cap_record.utterance_id,
                                          asr_hypothesis=text, duration_s=cap_record.duration_s)
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
            elif msg.type == WSMsgType.TEXT:
                # The one control message the browser sends us (everything else on this socket
                # is server → browser JSON events): the "record this session" toggle. Ignore
                # anything malformed rather than tearing down the session over a bad control frame.
                try:
                    ctrl = json.loads(msg.data)
                except ValueError:
                    continue
                if ctrl.get("type") == "control" and ctrl.get("capture"):
                    session.enable_capture()
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        session.stop()
        pump_task.cancel()
        active["session"] = None
    return ws


async def corrections_handler(request: web.Request) -> web.Response:
    """POST /corrections — human-in-the-loop ground truth for a captured session.

    Body: {"session_id": "...", "corrections": [{"utterance_id": "...", "ground_truth": "..."}]}.
    Looked up via the module-level CAPTURES registry (not `active["session"]`) so this works
    after the WebSocket has closed — the whole point of the UI flow is "stop talking, THEN
    review and correct," and by then session.capture may already be an orphaned reference.
    """
    try:
        body = await request.json()
    except (ValueError, TypeError) as e:
        return web.json_response({"ok": False, "error": f"invalid JSON body: {e}"}, status=400)

    session_id = body.get("session_id")
    capture = CAPTURES.get(session_id)
    if capture is None:
        return web.json_response({"ok": False, "error": f"unknown session_id {session_id!r}"}, status=404)

    applied: list[str] = []
    unknown: list[str] = []
    for item in body.get("corrections", []):
        utterance_id = item.get("utterance_id")
        ground_truth = item.get("ground_truth", "")
        if utterance_id and capture.apply_correction(utterance_id, ground_truth):
            applied.append(utterance_id)
        else:
            unknown.append(utterance_id)
    return web.json_response({"ok": True, "applied": applied, "unknown": unknown})


def main() -> None:
    load_repo_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--quantized", type=int, choices=[4, 8], default=4,
                    help="4 is the default by measurement: q8 misses the 80 ms budget on M5 "
                         "(p95 91 ms vs q4's 50 ms) and smoothness beats bits for clarity")
    ap.add_argument("--hf-repo", default=None)
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--temp", type=float, default=0.8, help="audio sampling temperature (0.6 = cleaner/flatter)")
    ap.add_argument("--port", type=int, default=8990)
    ap.add_argument("--no-model", action="store_true",
                     help="skip loading Moshi entirely — ASR/brain/capture only. For developing/testing "
                          "the capture feature without a GPU-heavy model load (never run Moshi and this "
                          "flag at once from the same invocation; see docs/DECISIONS.md 0008 on contention).")
    ap.add_argument("--capture", action="store_true",
                     help="opt-in session recording, ON for every session from server start (off by "
                          "default). The web UI also has a per-session toggle for the same thing.")
    args = ap.parse_args()
    if args.hf_repo is None and not args.no_model:
        from duet_agent import local_loop  # deferred — see the import note near FRAME above
        args.hf_repo = local_loop.DEFAULT_REPOS[args.quantized]

    app = web.Application()
    app["args"] = args
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/corrections", corrections_handler)
    app.router.add_get("/", lambda r: web.FileResponse(STATIC / "index.html"))
    app.router.add_static("/static", STATIC)
    mode = "NO-MODEL (ASR/brain/capture only)" if args.no_model else f"model: {args.hf_repo}"
    print(f"Duet web demo → http://localhost:{args.port}  ({mode}, capture default {'ON' if args.capture else 'off'})")
    web.run_app(app, port=args.port, print=None)


if __name__ == "__main__":
    main()
