#!/usr/bin/env python3
# Duet web demo — talk to the hybrid SDR agent from a browser instead of a terminal.
#
# Why a browser: getUserMedia gives echo cancellation + noise suppression for
# free (the terminal demo's raw audio path has neither — speakers made Moshi
# hear itself), and the page shows everything that used to be invisible:
# your live transcript, Duet's words as it speaks them, a safe decision trace
# (never private chain-of-thought), grounded sources, and audio levels.
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
import base64
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from duet_agent.asr import SileroSpeechDetector, load_asr, meaningful_text  # noqa: E402
from duet_agent.asr_util import to_whisper_rate  # noqa: E402
from duet_agent.actions import ActionLayer  # noqa: E402
from duet_agent.env import load_repo_env  # noqa: E402
from duet_agent.injector import TextInjector  # noqa: E402
from duet_agent.live_telemetry import LiveSessionTelemetry, METRICS  # noqa: E402
from duet_agent import persona  # noqa: E402
from duet_agent.rate_limits import SessionAdmission, gemini_quota  # noqa: E402
from duet_agent.reasoning import Guidance, ReasoningFailure, ReasoningLayer, SpeechPreview  # noqa: E402
from duet_agent.turns import TurnAssembler  # noqa: E402

from capture import SessionCapture, UtteranceSegmenter  # noqa: E402 — pure; safe under --no-model

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
    """One live conversation: voice thread + brain thread (VAD/ASR + reasoning)."""

    def __init__(self, args):
        self.args = args
        self.mic_q: queue.Queue = queue.Queue(maxsize=64)    # browser → model
        self.spk_q: queue.Queue = queue.Queue(maxsize=64)    # model → browser
        self.events: queue.Queue = queue.Queue()             # JSON events → browser
        self.tap_q: queue.Queue = queue.Queue(maxsize=256)   # WebSocket mic copy → brain (independent of model load)
        self.speech_q: queue.Queue = queue.Queue()           # text → local TTS voice
        self.running = True
        self.agent_speaking = threading.Event()
        self.cancel_speech = threading.Event()
        self.listen_after = 0.0
        self.injector: TextInjector | None = None
        self.step_ms: list[float] = []
        self.sdr_started = False
        self.sdr_permission = "pending"
        self.sdr_opted_out = False
        self.barge_in_pending = False
        self.sdr_clarification_pending = False
        self.sdr_clarification_attempts = 0
        self.current_speech_text = ""
        self._speech_seq = 0
        self.latest_brain_request_id = 0
        self.speculative_request_id = 0
        self.speculative_text = ""
        self.speculative_committed_ids: set[int] = set()
        self.speculative_results: dict[int, object] = {}
        self.ready_brain_results = deque()
        self.pending_speech_previews: dict[int, SpeechPreview] = {}
        self.early_spoken_ids: set[int] = set()
        self.lead_signals = {dimension: "none" for dimension in persona.BANT}
        self.lead_evidence = {dimension: None for dimension in persona.BANT}
        self.recent_agent_responses = deque(maxlen=4)
        # session capture — opt-in only; see enable_capture(). session_id doubles as the
        # eval/asr/sessions/<session_id>/ directory name once capture is turned on.
        self.session_id = f"{int(time.time())}-{os.urandom(3).hex()}"
        self.action_layer = ActionLayer(self.session_id)
        self.brain = None
        self.telemetry = LiveSessionTelemetry(
            self.session_id,
            "sdr",
            {
                "voice_stack": args.voice_stack,
                "asr": args.asr,
                "tts": args.tts_backend,
                "barge_in": args.barge_in,
            },
        )
        self.capture: SessionCapture | None = None
        if getattr(args, "capture", False):
            self.enable_capture()

    def emit(self, **ev) -> None:
        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            telemetry.event(ev)
        self.events.put(ev)

    def enable_capture(self) -> None:
        """Turn on session recording. Idempotent — a second call (e.g. CLI --capture plus a
        redundant UI toggle) is a no-op, not a second directory."""
        if self.capture is not None:
            return
        self.capture = SessionCapture(SESSIONS_DIR / self.session_id, min_rms_threshold=self.args.asr_min_rms)
        CAPTURES[self.session_id] = self.capture
        self.emit(type="capture_status", enabled=True, session_id=self.session_id)

    def start(self) -> None:
        threading.Thread(target=self._model_loop, daemon=True).start()
        threading.Thread(target=self._brain_loop, daemon=True).start()

    def stop(self, reason: str = "client_disconnect") -> None:
        if not self.running:
            return
        self.running = False
        self.cancel_speech.set()
        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            telemetry.finish(reason, getattr(self, "brain", None))

    @staticmethod
    def _clear_queue(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def interrupt_playback(self, transcript: str = "") -> None:
        """Stop current and buffered speech when verified user speech arrives."""
        if (
            not self.args.barge_in
            or not self.agent_speaking.is_set()
            or self.cancel_speech.is_set()
        ):
            return
        self.cancel_speech.set()
        self._clear_queue(self.spk_q)
        self._clear_queue(self.speech_q)
        self.emit(type="playback_cancel", reason="user_barge_in", transcript=transcript)
        self.emit(type="status", text="interruption detected — Duet yielded the floor")

    def handle_speech_start(self) -> None:
        """Yield immediately on provider VAD, before a final transcript exists.

        Browser echo cancellation is the first defence against self-echo.  The
        semantic transcript still decides what happens next; this method only
        gives the acoustic floor to the caller.
        """
        if self.args.barge_in and self.agent_speaking.is_set():
            self.barge_in_pending = True
            self.interrupt_playback("")

    def handle_final_during_playback(self, text: str) -> None:
        """Second barge-in guard when provider VAD arrives after a final.

        Provider VAD is normally faster, but an utterance that begins close to
        an audio boundary can reach us first as a final. Without this guard it
        is accepted while the prior answer continues, queues a second answer,
        and makes the call sound lost. Backchannels remain non-interrupting.
        """
        if not self.args.barge_in or not self.agent_speaking.is_set():
            return
        if persona.is_backchannel(text):
            return
        permission = persona.permission_response(text) if self.sdr_permission == "pending" else None
        if permission or persona.should_interrupt(text, self.current_speech_text):
            self.barge_in_pending = True
            self.interrupt_playback(text)

    # -- the 80 ms heartbeat ------------------------------------------------

    def _model_loop(self) -> None:
        if self.args.voice_stack == "open":
            self._open_voice_loop()
            return
        if self.args.voice_stack == "none":
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
        last_health_warning = 0.0
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
                p50 = round(float(np.percentile(arr, 50)), 1)
                p95 = round(float(np.percentile(arr, 95)), 1)
                miss_rate = round(float(np.mean(arr > 80.0)), 3)
                degraded = p95 > 80.0 or miss_rate > 0.05
                self.emit(type="stats", p50=p50, p95=p95, frames=len(self.step_ms),
                          miss_rate=miss_rate, degraded=degraded)
                if degraded and time.time() - last_health_warning > 10:
                    self.emit(type="status", text=f"⚠ realtime budget missed: p95 {p95} ms, {miss_rate:.0%} frames over 80 ms")
                    last_health_warning = time.time()
                last_stats = time.time()

    def _model_loop_stub(self) -> None:
        """--no-model path: no mlx/moshi_mlx/rustymimi import, no weights, no GPU memory —
        required so --capture can be developed/tested without a model load while another
        process may be using the GPU (docs/DECISIONS.md 0008 on resource contention). Mic
        frames flow directly from the WebSocket to the brain's tap_q; there's no mouth to speak back,
        so the speaker stays silent and no `duet`/`stats` events are ever emitted."""
        self.emit(type="status", text="--no-model: Moshi skipped — ASR/brain/capture only", ready=True)
        while self.running:
            try:
                self.mic_q.get(timeout=0.5)
            except queue.Empty:
                continue

    def _open_voice_loop(self) -> None:
        """Streaming cascade mouth with optional, explicitly controlled barge-in.

        The default remains half-duplex because browser AEC is not a correctness
        boundary.  With ``--barge-in``, Sarvam continues listening and a
        meaningful partial transcript cancels current and buffered playback.
        """
        from duet_agent import tts

        self.emit(type="status", text=f"loading {self.args.tts_backend} voice …")
        try:
            voice = tts.load(self.args.tts_backend)
            warm = getattr(voice, "warm", None)
            if warm is not None:
                warm()
        except Exception as e:
            self.emit(type="error", text=f"local TTS unavailable: {type(e).__name__}: {e}")
            return
        vad_label = "Sarvam streaming VAD" if self.args.asr == "sarvam" else "Silero VAD"
        self.emit(
            type="status",
            text=(
                f"ready — voice stack ({self.args.asr}, {vad_label}, {voice.name} TTS"
                + (
                    f": {voice.speaker}, pace {voice.pace:.2f}"
                    + (f", warmth {voice.temperature:.2f}" if getattr(voice, "temperature", None) is not None else "")
                    if voice.name.startswith("sarvam") else ""
                )
                + ")"
            ),
            ready=True,
        )
        self._start_sdr()
        while self.running:
            try:
                speech_item = self.speech_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(speech_item, tuple):
                utterance_id, text = speech_item
            else:  # compatibility with old queues and narrow unit tests
                utterance_id, text = 0, speech_item
            self.cancel_speech.clear()
            self.agent_speaking.set()
            self.current_speech_text = text
            if self.args.barge_in:
                self.emit(type="asr_state", state="listening", speech=False, streaming=True, barge_in=True)
            else:
                self.emit(type="asr_state", state="paused", reason="Duet is speaking")
            self.emit(type="tts_state", state="speaking", backend=voice.name, text=text, utterance_id=utterance_id)
            try:
                tts_started = time.perf_counter()
                first_audio = True
                audio_chunks = voice.synthesize_stream(text)
                frames = tts.iter_pcm_frames(audio_chunks, FRAME)
                frame_period = FRAME / 24_000
                next_frame_at = time.perf_counter()
                for frame in frames:
                    if self.cancel_speech.is_set():
                        break
                    if first_audio:
                        self.emit(
                            type="tts_state",
                            state="first_audio",
                            backend=voice.name,
                            latency_ms=round((time.perf_counter() - tts_started) * 1000),
                            utterance_id=utterance_id,
                        )
                        first_audio = False
                    while self.running:
                        if self.cancel_speech.is_set():
                            break
                        try:
                            self.spk_q.put(frame, timeout=0.5)
                            break
                        except queue.Full:
                            continue
                    # Pace against an absolute clock. Sleeping a full frame after
                    # every provider read compounds socket and scheduler delay and
                    # creates browser underruns; this catches that time up without
                    # dumping an entire utterance into the client buffer.
                    next_frame_at += frame_period
                    now = time.perf_counter()
                    if next_frame_at < now - (3 * frame_period):
                        next_frame_at = now
                    elif next_frame_at > now:
                        time.sleep(next_frame_at - now)
            except Exception as e:
                self.emit(type="error", text=f"TTS failed: {type(e).__name__}: {e}")
            finally:
                # Generator.close() propagates cancellation into persistent TTS,
                # which drops unread provider audio before the next utterance.
                if "frames" in locals() and hasattr(frames, "close"):
                    frames.close()
                interrupted = self.cancel_speech.is_set()
                if not interrupted:
                    # Half-duplex needs an echo tail. In barge-in mode the mic is
                    # already live, so only normal completion gets a short tail.
                    time.sleep(0.15 if self.args.barge_in else 0.45)
                self.listen_after = time.monotonic() + (0.05 if self.args.barge_in else 0.25)
                self.agent_speaking.clear()
                self.current_speech_text = ""
                self.emit(
                    type="tts_state",
                    state="interrupted" if interrupted else "listening",
                    backend=voice.name,
                    utterance_id=utterance_id,
                )
        close_voice = getattr(voice, "close", None)
        if close_voice is not None:
            close_voice()

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.args.voice_stack == "open":
            self.agent_speaking.set()
            self._speech_seq = getattr(self, "_speech_seq", 0) + 1
            self.emit(type="duet", text=text, utterance_id=self._speech_seq)
            self.speech_q.put((self._speech_seq, text))
        elif self.injector is not None:
            self.injector.inject(text)

    def _start_sdr(self) -> None:
        """Begin a consented-lead callback with deterministic AI disclosure."""
        if self.sdr_started:
            return
        self.sdr_started = True
        self.speak(persona.OPENING)
        self.emit(
            type="policy",
            state="permission_pending",
            text="AI identity disclosed; waiting for permission before discovery",
        )

    # -- the slow brain -------------------------------------------------------

    def _brain_loop(self) -> None:
        brain = self._make_brain()
        self.brain = brain
        if self.args.asr == "sarvam":
            completed = asyncio.run(self._sarvam_brain_loop(brain))
            if completed or not self.running:
                return
            self.emit(type="status", text="Sarvam stream unavailable — falling back to local Parakeet")
            self.args.asr = "parakeet"
        self._local_brain_loop(brain)

    def _make_brain(self):
        try:
            brain = ReasoningLayer()
            telemetry = getattr(self, "telemetry", None)
            if telemetry is not None:
                telemetry.attach_brain(brain)
            return brain
        except RuntimeError as e:
            self.emit(type="status", text=f"brain disabled: {e}")
        return None

    def _start_speculative_reasoning(self, text: str, history, brain) -> None:
        """Start reasoning on a stable interim, but never speak before commit."""
        if (
            brain is None
            or self.sdr_permission != "granted"
            or self.sdr_opted_out
            or persona.is_opt_out(text)
            or persona.is_ambiguous_change(text)
            or persona.is_backchannel(text)
            or len(persona.normalized_words(text)) < 4
        ):
            return
        if getattr(self, "speculative_request_id", 0):
            return
        request_id = brain.request(history, text)
        self.speculative_request_id = request_id
        self.speculative_text = text
        self.emit(
            type="brain_state",
            state="speculating",
            request_id=request_id,
            text="Stable interim sent to reasoning; speech remains gated until final transcript",
        )

    def _commit_or_replace_speculation(self, text: str, history, brain) -> None:
        request_id = getattr(self, "speculative_request_id", 0)
        speculative_text = getattr(self, "speculative_text", "")
        if request_id and persona.partial_matches_final(speculative_text, text):
            self.latest_brain_request_id = request_id
            self.speculative_committed_ids.add(request_id)
            cached = self.speculative_results.pop(request_id, None)
            if cached is not None:
                self.ready_brain_results.append(cached)
            self.emit(
                type="brain_state",
                state="speculation_committed",
                request_id=request_id,
                text="Final transcript confirmed the speculative reasoning input",
            )
        elif brain:
            self.latest_brain_request_id = brain.request(history, text)
            if request_id:
                self.emit(
                    type="brain_state",
                    state="speculation_replaced",
                    request_id=request_id,
                    text="Final transcript changed meaning; speculative result was discarded",
                )
        self.speculative_request_id = 0
        self.speculative_text = ""

    def _accept_transcript(self, text, latency_ms, history, brain, cap_record=None) -> None:
        raw_text = text.strip()
        accepted = meaningful_text(raw_text)
        text = persona.normalize_domain_terms(raw_text) if accepted else raw_text
        self.emit(
            type="asr_state",
            state="result",
            latency_ms=round(latency_ms),
            text=text if accepted else "",
            raw_text=raw_text if accepted and raw_text != text else "",
        )
        if not accepted:
            self.emit(type="status", text="ASR output rejected: no meaningful words")
            return
        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            telemetry.mark_user_turn(float(latency_ms))
        self.emit(type="you", text=text, raw_text=raw_text if raw_text != text else "")
        if self.capture is not None and cap_record is not None:
            self._attach_capture(cap_record, raw_text)
        if self.args.mode == "sdr":
            history.append(("lead", text))
            if self.sdr_opted_out:
                return
            if persona.is_opt_out(text):
                self.sdr_opted_out = True
                self.sdr_permission = "denied"
                self.interrupt_playback(text)
                self.speak(persona.OPT_OUT_ACK)
                self.emit(type="policy", state="do_not_contact", text="Opt-out detected; sales reasoning disabled")
                return
            if getattr(self, "sdr_clarification_pending", False):
                resolution = persona.clarification_response(text)
                if resolution == "stop":  # defensive: explicit opt-out is handled above
                    self.sdr_opted_out = True
                    self.sdr_permission = "denied"
                    self.speak(persona.OPT_OUT_ACK)
                    return
                if resolution == "pause":
                    self.sdr_clarification_pending = False
                    self.sdr_clarification_attempts = 0
                    self.barge_in_pending = False
                    self.speak(persona.PAUSE_ACK)
                    history.append(("agent", persona.PAUSE_ACK))
                    self.emit(type="policy", state="interruption_paused", text="Caller retained the floor")
                    return
                if resolution == "resolved":
                    # The caller supplied the missing preference or question.
                    # Clear the repair state and let this *same* turn reach the
                    # normal safety gates and planner; never throw it away.
                    self.sdr_clarification_pending = False
                    self.sdr_clarification_attempts = 0
                    self.barge_in_pending = False
                    self.emit(
                        type="policy",
                        state="interruption_resolved",
                        text="Explicit caller intent resumed normal reasoning",
                    )
                if resolution == "continue":
                    self.sdr_clarification_pending = False
                    self.sdr_clarification_attempts = 0
                    response = "Thanks for clarifying. What would you like to change?"
                    self.speak(response)
                    history.append(("agent", response))
                    self.emit(type="policy", state="interruption_resolved", text="Caller chose to continue")
                    self.barge_in_pending = False
                    return
                if resolution is None:
                    # Do not machine-gun the same repair prompt for "yeah" or
                    # "hmm".  Ask one more, more concrete question, then wait
                    # silently for a meaningful turn while keeping the floor.
                    attempts = getattr(self, "sdr_clarification_attempts", 0)
                    if not persona.is_backchannel(text) and attempts == 0:
                        response = persona.INTERRUPTION_CLARIFICATION_FOCUSED
                        self.speak(response)
                        history.append(("agent", response))
                    self.sdr_clarification_attempts = attempts + 1
                    self.emit(
                        type="policy",
                        state="clarification_waiting",
                        text="Waiting for an explicit preference or question; no repeated pitch",
                    )
                    self.barge_in_pending = False
                    return
            if self.sdr_permission == "pending":
                permission = persona.permission_response(text)
                if permission == "granted":
                    self.sdr_permission = "granted"
                    response = "Thank you. Would this be mainly a home for your family, or an investment?"
                    self.speak(response)
                    history.append(("agent", response))
                    self.emit(type="policy", state="permission_granted", text="Discovery may proceed")
                elif permission == "denied":
                    self.sdr_permission = "denied"
                    self.speak(persona.NOT_NOW_ACK)
                    self.emit(type="policy", state="permission_denied", text="Conversation stopped before sales discovery")
                else:
                    response = "Before we continue, would you like to have this brief conversation now?"
                    self.speak(response)
                    history.append(("agent", response))
                return
            if self.sdr_permission != "granted":
                return
            # Acoustic barge-in and semantic intent are separate decisions. A
            # caller asking for a moment should hear that Aira yielded; a vague
            # fragment must be clarified; a complete question can proceed to
            # the planner normally. Silence after a successful cancellation is
            # technically correct but conversationally broken.
            if getattr(self, "barge_in_pending", False):
                self.barge_in_pending = False
                if persona.is_pause_request(text):
                    self.speak(persona.PAUSE_ACK)
                    history.append(("agent", persona.PAUSE_ACK))
                    self.emit(
                        type="policy",
                        state="interruption_acknowledged",
                        text="Aira yielded and acknowledged the caller's pause request",
                    )
                    return
                if persona.is_presence_check(text):
                    self.speak(persona.PRESENCE_ACK)
                    history.append(("agent", persona.PRESENCE_ACK))
                    self.emit(
                        type="policy",
                        state="presence_confirmed",
                        text="Aira confirmed the connection without restarting the pitch",
                    )
                    return
                if persona.needs_interruption_clarification(text):
                    self.sdr_clarification_pending = True
                    self.sdr_clarification_attempts = 0
                    self.speak(persona.INTERRUPTION_CLARIFICATION)
                    history.append(("agent", persona.INTERRUPTION_CLARIFICATION))
                    self.emit(
                        type="policy",
                        state="clarification_required",
                        text="Vague barge-in changed the floor but not the conversational intent",
                    )
                    return
            if persona.is_ambiguous_change(text):
                self.sdr_clarification_pending = True
                self.sdr_clarification_attempts = 0
                self.barge_in_pending = False
                self.speak(persona.INTERRUPTION_CLARIFICATION)
                history.append(("agent", persona.INTERRUPTION_CLARIFICATION))
                self.emit(
                    type="policy",
                    state="clarification_required",
                    text="Ambiguous change after interruption; planner was not called",
                )
                return
            if persona.is_sensitive_profiling_request(text):
                self.speak(persona.SENSITIVE_PROFILE_ACK)
                history.append(("agent", persona.SENSITIVE_PROFILE_ACK))
                self.emit(
                    type="policy",
                    state="sensitive_profiling_blocked",
                    text="Sensitive traits cannot be used for purchase scoring or persuasion",
                )
                return
            if persona.is_backchannel(text):
                self.emit(
                    type="policy",
                    state="listener_backchannel",
                    text="Acknowledgment heard; Aira waits instead of starting another pitch",
                )
                return
            if persona.needs_low_information_repair(text):
                response = persona.LOW_INFORMATION_REPAIR
                self.speak(response)
                history.append(("agent", response))
                self.emit(
                    type="policy",
                    state="low_information_repair",
                    text="Short final was not sent to sales reasoning; Aira asked one concrete recovery question",
                )
                return
            if brain:
                self._commit_or_replace_speculation(text, history[:-1], brain)
            return
        if brain:
            brain.request(history, text)
        history.append(("lead", text))

    def _attach_capture(self, cap_record, text: str) -> None:
        if self.capture is None:
            return
        self.capture.set_hypothesis(cap_record.utterance_id, text)
        self.emit(
            type="captured",
            utterance_id=cap_record.utterance_id,
            asr_hypothesis=text,
            duration_s=cap_record.duration_s,
        )

    def _poll_brain(self, brain, history) -> None:
        if not brain:
            return
        self._poll_brain_preview(brain, history)
        ready = getattr(self, "ready_brain_results", None)
        result = ready.popleft() if ready else brain.poll()
        if self.args.mode == "sdr" and self.sdr_opted_out:
            return
        request_id = getattr(result, "request_id", 0)
        speculative_id = getattr(self, "speculative_request_id", 0)
        committed = getattr(self, "speculative_committed_ids", set())
        if result is not None and request_id and request_id == speculative_id and request_id not in committed:
            self.speculative_results[request_id] = result
            self.emit(
                type="brain_state",
                state="speculation_ready",
                request_id=request_id,
                text="Reasoning ready but held until the final transcript confirms it",
            )
            return
        if isinstance(result, Guidance):
            if not hasattr(self, "lead_signals"):
                self.lead_signals = {dimension: "none" for dimension in persona.BANT}
                self.lead_evidence = {dimension: None for dimension in persona.BANT}
                self.recent_agent_responses = deque(maxlen=4)
            request_id = getattr(result, "request_id", 0)
            latest = getattr(self, "latest_brain_request_id", 0)
            if request_id and latest and request_id < latest:
                self.emit(
                    type="policy",
                    state="stale_reasoning_suppressed",
                    text=f"Dropped response {request_id}; the conversation has moved to turn {latest}",
                )
                return

            rank = {"none": 0, "weak": 1, "strong": 2}
            for dimension in persona.BANT:
                incoming = result.lead_signals.get(dimension, "none")
                if rank[incoming] > rank[getattr(self, "lead_signals", {}).get(dimension, "none")]:
                    self.lead_signals[dimension] = incoming
                evidence = result.lead_evidence.get(dimension)
                if evidence:
                    self.lead_evidence[dimension] = evidence

            spoken = result.talking_point.strip()
            policy_check = "passed"
            problem = persona.response_problem(spoken) if spoken else None
            tool_requests = result.tool_requests or (
                [result.tool_request] if result.tool_request is not None else []
            )
            if tool_requests:
                action_layer = getattr(self, "action_layer", None)
                if action_layer is None:
                    action_layer = ActionLayer(getattr(self, "session_id", "test-session"))
                    self.action_layer = action_layer
                action_ids = []
                for tool_request in tool_requests:
                    action_id = action_layer.request(tool_request)
                    action_ids.append(action_id)
                    self.emit(
                        type="action",
                        state="requested",
                        name=tool_request.name,
                        action_id=action_id,
                        enabled=action_layer.enabled,
                        adapter=action_layer.capability_label,
                    )
                if problem == "unavailable_tool_claim" or not spoken:
                    spoken = (
                        "Certainly. I am putting those requests through now."
                        if len(tool_requests) > 1 else "Certainly. I am putting that request through now."
                    )
                # Purely transactional turns should speak the adapter's actual
                # accepted/completed result, not queue a generic promise and a
                # confirmation back-to-back. Preserve planner speech only when
                # it also carries a grounded project answer.
                if not result.fact_ids:
                    spoken = ""
                policy_check = (
                    f"{len(action_ids)} action request(s) sent through "
                    f"{action_layer.capability_label}; confirmation pending"
                )
            elif problem == "unavailable_tool_claim":
                spoken = (
                    "I can do that through ASBL's internal product once you explicitly ask me to."
                )
                policy_check = "completion claim blocked; no structured tool request"
            elif problem == "too_long_for_voice":
                spoken = " ".join(spoken.split()[:32]).rstrip(",;:") + "."
                policy_check = "shortened for speech"

            early_spoken = request_id in getattr(self, "early_spoken_ids", set())
            if spoken and not early_spoken and persona.is_repetitive_response(
                spoken, list(getattr(self, "recent_agent_responses", []))
            ):
                spoken = (
                    "I'm repeating myself. Let me reset. What would Broadway need to prove "
                    "before you would seriously consider it?"
                )
                policy_check = "repetition detected; reset question used"

            if result.response_strategy == "wait" and not early_spoken:
                # A model-level wait is appropriate only for a real continuer,
                # which is filtered before the planner. A final that reached
                # this point but yielded no speech otherwise feels like a
                # broken call, so repair the turn rather than going silent.
                spoken = persona.UNRESOLVED_TURN_REPAIR
                policy_check = "planner wait repaired with one clarification; caller was never left in silence"

            if spoken and not early_spoken:
                self.speak(spoken)
                history.append(("agent", spoken))
                self.recent_agent_responses.append(spoken)
            self.emit(
                type="brain",
                text=spoken,
                latency_ms=round(result.latency_ms),
                intent=result.intent,
                stage=result.conversation_stage,
                strategy=result.response_strategy,
                next_action=result.next_action,
                decision_summary=result.decision_summary,
                facts=persona.resolve_fact_ids(result.fact_ids),
                signals=self.lead_signals,
                evidence=self.lead_evidence,
                policy_check=policy_check,
                request_id=request_id,
                user_utterance=result.user_utterance,
            )
        elif isinstance(result, ReasoningFailure):
            self.emit(type="status", text=f"brain call failed ({result.reason[:60]}) — continuing unaided")

    def _poll_brain_preview(self, brain, history) -> None:
        """Release policy-checked speech before slower audit metadata completes."""
        poll_preview = getattr(brain, "poll_preview", None)
        pending = getattr(self, "pending_speech_previews", None)
        if pending is None:
            pending = {}
            self.pending_speech_previews = pending
        if poll_preview is not None:
            preview = poll_preview()
            if preview is not None:
                pending[preview.request_id] = preview

        latest = getattr(self, "latest_brain_request_id", 0)
        committed = getattr(self, "speculative_committed_ids", set())
        already_spoken = getattr(self, "early_spoken_ids", set())
        for request_id, preview in list(pending.items()):
            if request_id < latest and request_id not in committed:
                pending.pop(request_id, None)
                continue
            if request_id != latest and request_id not in committed:
                continue
            pending.pop(request_id, None)
            text = preview.text.strip()
            problem = persona.response_problem(text) if text else "empty"
            if (
                not text
                or problem is not None
                or persona.is_transactional_request(preview.user_utterance)
                or persona.is_repetitive_response(text, list(getattr(self, "recent_agent_responses", [])))
            ):
                self.emit(
                    type="brain_state",
                    state="early_speech_gated",
                    request_id=request_id,
                    text="Streamed speech waited for final policy or tool metadata",
                )
                continue
            if request_id in already_spoken or self.sdr_opted_out:
                continue
            self.speak(text)
            history.append(("agent", text))
            self.recent_agent_responses.append(text)
            already_spoken.add(request_id)
            self.early_spoken_ids = already_spoken
            self.emit(
                type="brain_state",
                state="early_speech",
                request_id=request_id,
                latency_ms=round(preview.latency_ms),
                text="Complete spoken field passed policy while audit metadata kept streaming",
            )

    def _poll_actions(self, history) -> None:
        layer = getattr(self, "action_layer", None)
        if layer is None:
            return
        result = layer.poll()
        if result is None:
            return
        if self.args.mode == "sdr" and self.sdr_opted_out:
            self.emit(type="action", state="confirmation_suppressed_after_opt_out", name=result.name)
            return
        spoken = result.spoken_confirmation
        self.speak(spoken)
        history.append(("agent", spoken))
        self.emit(
            type="action",
            state=result.status,
            name=result.name,
            reference_id=result.reference_id,
            latency_ms=round(result.latency_ms),
            reason=result.reason,
            adapter=result.adapter,
            text=spoken,
        )

    def _local_brain_loop(self, brain) -> None:
        try:
            asr = load_asr(self.args.asr)
            speech_detector = SileroSpeechDetector(
                threshold=self.args.vad_threshold,
                min_speech_ms=self.args.vad_min_speech_ms,
            )
            self.emit(type="asr_state", state="ready", model=asr.name, vad=speech_detector.name)
        except Exception as e:
            self.emit(type="status", text=f"ASR unavailable ({type(e).__name__}: {e}) — transcript disabled")
            asr = None
            speech_detector = None

        history: list[tuple[str, str]] = []
        segmenter = UtteranceSegmenter(min_rms_threshold=self.args.asr_min_rms)
        last_asr_state = 0.0
        while self.running:
            try:
                pcm = self.tap_q.get(timeout=0.5)
            except queue.Empty:
                pcm = None
            # Feed capture the SAME frame, in the SAME order, as the shared segmenter below —
            # both are instances of capture.UtteranceSegmenter, so they close on the same frame. That's
            # what lets `cap_record` below be the capture-side record for whatever text the ASR
            # branch produces this iteration, with no separate alignment bookkeeping needed.
            cap_record = self.capture.add_frame(pcm) if (pcm is not None and self.capture is not None) else None
            if pcm is not None and asr is not None and speech_detector is not None:
                audio = segmenter.add_frame(pcm)
                if time.time() - last_asr_state > 0.4:
                    self.emit(type="asr_state", state="calibrating" if segmenter.calibrating else "listening",
                              rms=round(segmenter.last_rms, 5), threshold=round(segmenter.threshold, 5),
                              speech=segmenter.active)
                    last_asr_state = time.time()
                if audio is not None:
                    speech_ms = speech_detector.speech_ms(audio)
                    if speech_ms < self.args.vad_min_speech_ms:
                        self.emit(
                            type="asr_state",
                            state="rejected",
                            reason="no human speech detected",
                            speech_ms=speech_ms,
                        )
                        continue
                    self.emit(
                        type="asr_state",
                        state="transcribing",
                        duration_s=round(len(audio) / 24_000, 2),
                        speech_ms=speech_ms,
                    )
                    try:
                        transcript = asr.transcribe(audio)
                        text = transcript.text
                    except Exception as e:
                        self.emit(type="status", text=f"ASR failed: {type(e).__name__}: {e}")
                        continue
                    self._accept_transcript(text, transcript.latency_ms, history, brain, cap_record)
            self._poll_brain(brain, history)
            self._poll_actions(history)

    async def _sarvam_brain_loop(self, brain) -> bool:
        if self.args.sarvam_stt == "realtime":
            completed = await self._sarvam_realtime_brain_loop(brain)
            if completed or not self.running:
                return completed
            self.emit(
                type="status",
                text="Sarvam realtime stream unavailable — trying the legacy stream",
            )
        return await self._sarvam_legacy_brain_loop(brain)

    async def _sarvam_realtime_brain_loop(self, brain) -> bool:
        """Current Saaras realtime protocol with true interims and provider VAD."""
        from websockets.asyncio.client import connect as websocket_connect

        api_key = os.environ.get("SARVAM_API_KEY", "")
        if not api_key:
            return False
        query = urlencode(
            {
                "language_code": self.args.sarvam_language,
                "stream_type": "fast",
                "endpointing": "vad",
                "encoding": "linear16",
                "sample_rate": 16000,
                "model": "saaras:v3-realtime",
                "mode": self.args.sarvam_mode,
                "return_timestamps": "false",
                "prefix_padding_ms": 200,
                "silence_duration_ms": self.args.sarvam_silence_ms,
                "min_speech_duration_ms": 100,
            }
        )
        url = f"wss://api.sarvam.ai/speech-to-text-realtime/ws?{query}"
        history: list[tuple[str, str]] = []
        capture_records = deque()
        pending_capture_text = deque()
        failures = 0

        while self.running and failures < 3:
            try:
                async with websocket_connect(
                    url,
                    additional_headers={"API-SUBSCRIPTION-KEY": api_key},
                ) as socket:
                    failures = 0
                    self.emit(
                        type="asr_state",
                        state="ready",
                        model="sarvam-saaras-v3-realtime",
                        vad="sarvam-realtime-vad",
                    )
                    audio_buffer = bytearray()
                    latest_partial = {"text": "", "changed_at": 0.0, "speech": False}
                    last_speech_end = {"at": None}

                    async def sender() -> None:
                        while self.running:
                            try:
                                pcm = await asyncio.to_thread(self.tap_q.get, True, 0.5)
                            except queue.Empty:
                                continue
                            if self.capture is not None:
                                record = self.capture.add_frame(pcm)
                                if record is not None:
                                    if pending_capture_text:
                                        self._attach_capture(record, pending_capture_text.popleft())
                                    else:
                                        capture_records.append(record)
                            audio16 = to_whisper_rate(pcm)
                            pcm16 = (np.clip(audio16, -1, 1) * 32767).astype(np.int16)
                            audio_buffer.extend(pcm16.tobytes())
                            # Upstream specifies a fixed 50 ms client cadence.
                            while len(audio_buffer) >= 1600:
                                chunk = bytes(audio_buffer[:1600])
                                del audio_buffer[:1600]
                                await socket.send(
                                    json.dumps(
                                        {
                                            "event": "audio_input",
                                            "audio": base64.b64encode(chunk).decode(),
                                        }
                                    )
                                )

                    async def receiver() -> None:
                        async for raw_message in socket:
                            if not isinstance(raw_message, str):
                                continue
                            message = json.loads(raw_message)
                            event = message.get("event")
                            now = time.monotonic()
                            if event == "vad.speech_start":
                                latest_partial.update(text="", changed_at=now, speech=True)
                                self.handle_speech_start()
                                self.emit(type="asr_state", state="listening", speech=True, streaming=True)
                            elif event == "vad.speech_end":
                                latest_partial["speech"] = False
                                last_speech_end["at"] = now
                                self._start_speculative_reasoning(latest_partial["text"], history, brain)
                                self.emit(type="asr_state", state="endpoint", streaming=True)
                            elif event == "transcript.partial":
                                text = str(message.get("text") or "").strip()
                                if text and text != latest_partial["text"]:
                                    latest_partial.update(text=text, changed_at=now)
                                    self.emit(type="asr_state", state="partial", text=text, streaming=True)
                            elif event == "transcript.final":
                                text = str(message.get("text") or "").strip()
                                self.handle_final_during_playback(text)
                                end_at = last_speech_end["at"] or now
                                record = capture_records.popleft() if capture_records else None
                                if self.capture is not None and record is None:
                                    pending_capture_text.append(text)
                                self._accept_transcript(
                                    text,
                                    (now - end_at) * 1000,
                                    history,
                                    brain,
                                    record,
                                )
                                latest_partial.update(text="", changed_at=0.0, speech=False)
                            elif event == "error":
                                raise RuntimeError(f"Sarvam realtime STT error: {message}")
                            elif event == "session.end":
                                return

                    async def coordinator() -> None:
                        while self.running:
                            now = time.monotonic()
                            partial = latest_partial["text"]
                            if (
                                latest_partial["speech"]
                                and partial
                                and now - latest_partial["changed_at"] >= 0.12
                            ):
                                self._start_speculative_reasoning(partial, history, brain)
                            self._poll_brain(brain, history)
                            self._poll_actions(history)
                            await asyncio.sleep(0.03)

                    tasks = [
                        asyncio.create_task(sender()),
                        asyncio.create_task(receiver()),
                        asyncio.create_task(coordinator()),
                    ]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    for task in done:
                        task.result()
                    if not self.running:
                        return True
            except Exception as e:
                failures += 1
                self.emit(
                    type="status",
                    text=f"Sarvam realtime stream disconnected ({type(e).__name__}); reconnecting {failures}/3",
                )
                await asyncio.sleep(min(0.5 * 2 ** (failures - 1), 2.0))
        return not self.running

    async def _sarvam_legacy_brain_loop(self, brain) -> bool:
        """Persistent streaming ASR with provider-independent turn assembly.

        Returns True after a normal session lifetime.  False means the stream
        failed repeatedly and the caller should start the local fallback.
        """
        from sarvamai import AsyncSarvamAI

        api_key = os.environ.get("SARVAM_API_KEY", "")
        if not api_key:
            self.emit(type="status", text="SARVAM_API_KEY missing — cannot start streaming ASR")
            return False

        history: list[tuple[str, str]] = []
        assembler = TurnAssembler(continuation_grace_s=self.args.turn_grace_ms / 1000)
        capture_records = deque()
        pending_capture_text = deque()
        failures = 0

        while self.running and failures < 3:
            client = AsyncSarvamAI(api_subscription_key=api_key)
            try:
                async with client.speech_to_text_streaming.connect(
                    model="saaras:v3",
                    mode=self.args.sarvam_mode,
                    language_code=self.args.sarvam_language,
                    sample_rate="16000",
                    input_audio_codec="pcm_s16le",
                    high_vad_sensitivity="false",
                    vad_signals="true",
                    flush_signal="true",
                ) as socket:
                    failures = 0
                    assembler.reset()
                    self.emit(type="asr_state", state="ready", model="sarvam-saaras-v3", vad="sarvam-vad")
                    last_speech_end = {"at": None}

                    async def sender() -> None:
                        while self.running:
                            try:
                                pcm = await asyncio.to_thread(self.tap_q.get, True, 0.5)
                            except queue.Empty:
                                continue
                            if self.capture is not None:
                                record = self.capture.add_frame(pcm)
                                if record is not None:
                                    if pending_capture_text:
                                        self._attach_capture(record, pending_capture_text.popleft())
                                    else:
                                        capture_records.append(record)
                            audio16 = to_whisper_rate(pcm)
                            pcm16 = (np.clip(audio16, -1, 1) * 32767).astype(np.int16)
                            encoded = base64.b64encode(pcm16.tobytes()).decode()
                            # The SDK's AudioData schema still says audio/wav, while the
                            # connection-level codec correctly declares this payload as raw PCM.
                            await socket.transcribe(audio=encoded, encoding="audio/wav", sample_rate=16_000)

                    async def receiver() -> None:
                        while self.running:
                            message = await socket.recv()
                            now = time.monotonic()
                            if message.type == "events":
                                signal = str(message.data.signal_type).upper()
                                if signal.endswith("START_SPEECH"):
                                    self.handle_speech_start()
                                    assembler.speech_started()
                                    self.emit(type="asr_state", state="listening", speech=True, streaming=True)
                                elif signal.endswith("END_SPEECH"):
                                    assembler.speech_ended(now)
                                    last_speech_end["at"] = now
                                    self.emit(type="asr_state", state="endpoint", streaming=True)
                            elif message.type == "data":
                                text = str(message.data.transcript).strip()
                                if (
                                    self.agent_speaking.is_set()
                                    and meaningful_text(text)
                                    and persona.should_interrupt(text, self.current_speech_text)
                                ):
                                    self.interrupt_playback(text)
                                assembler.add_transcript(text, now)
                                self.emit(type="asr_state", state="partial", text=text, streaming=True)

                    async def finalizer() -> None:
                        while self.running:
                            now = time.monotonic()
                            text = assembler.poll(now)
                            if text:
                                end_at = last_speech_end["at"] or now
                                latency_ms = (now - end_at) * 1000
                                record = capture_records.popleft() if capture_records else None
                                if self.capture is not None and record is None:
                                    pending_capture_text.append(text)
                                self._accept_transcript(text, latency_ms, history, brain, record)
                            self._poll_brain(brain, history)
                            self._poll_actions(history)
                            await asyncio.sleep(0.03)

                    tasks = [
                        asyncio.create_task(sender()),
                        asyncio.create_task(receiver()),
                        asyncio.create_task(finalizer()),
                    ]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    for task in done:
                        task.result()
                    if not self.running:
                        return True
            except Exception as e:
                failures += 1
                self.emit(
                    type="status",
                    text=f"Sarvam stream disconnected ({type(e).__name__}); reconnecting {failures}/3",
                )
                await asyncio.sleep(min(0.5 * 2 ** (failures - 1), 2.0))
        return not self.running


active: dict = {"session": None}


def _client_id(request: web.Request) -> str:
    """Return the admission-control key without trusting spoofable headers.

    Caddy appends X-Forwarded-For.  It is considered only when the operator has
    explicitly declared that this process sits behind a trusted proxy.
    """
    if os.environ.get("TRUST_PROXY", "false").lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:80]
    return (request.remote or "unknown")[:80]


def _origin_allowed(request: web.Request) -> bool:
    configured = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not configured:
        return True
    allowed = {origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()}
    return request.headers.get("Origin", "").rstrip("/") in allowed


async def ws_handler(request: web.Request) -> web.StreamResponse:
    if not _origin_allowed(request):
        METRICS.inc("duet_session_rejections_total", labels={"reason": "origin"},
                    help_text="Public session admission rejections")
        return web.json_response({"ok": False, "error": "origin not allowed"}, status=403)

    client_id = _client_id(request)
    allowed, retry_after, dimension = request.app["session_admission"].allow(client_id)
    if not allowed:
        METRICS.inc("duet_session_rejections_total", labels={"reason": dimension},
                    help_text="Public session admission rejections")
        return web.json_response(
            {"ok": False, "error": f"session {dimension} limit reached", "retry_after_s": round(retry_after)},
            status=429,
            headers={"Retry-After": str(max(1, round(retry_after)))},
        )

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

    async def enforce_session_cap() -> None:
        await asyncio.sleep(session.args.session_max_seconds)
        if not session.running:
            return
        message = "That's the demo limit — thanks for trying Aira. We'll be in touch."
        session.emit(type="policy", state="session_limit", text="Server-side session duration cap reached")
        session.speak(message)
        # Give the short closing line time to leave the server before disconnect.
        await asyncio.sleep(4)
        session.stop("session_limit")
        await ws.close(code=1000, message=b"session limit")

    cap_task = asyncio.create_task(enforce_session_cap())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY and len(msg.data) == FRAME * 4:
                pcm = np.frombuffer(msg.data, np.float32).copy()
                if session.args.voice_stack == "moshi":
                    try:
                        session.mic_q.put_nowait(pcm)
                    except queue.Full:
                        pass
                # In controlled barge-in mode browser AEC plus meaningful partial
                # ASR is the interruption gate. The default retains the stronger
                # half-duplex correctness boundary.
                admit_mic = session.args.barge_in or (
                    not session.agent_speaking.is_set() and time.monotonic() >= session.listen_after
                )
                if admit_mic:
                    try:
                        session.tap_q.put_nowait(pcm)
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
        session.stop("client_disconnect")
        pump_task.cancel()
        cap_task.cancel()
        active["session"] = None
    return ws


async def session_capacity_handler(request: web.Request) -> web.Response:
    """Explain capacity before the browser opens a microphone/WebSocket session."""
    client_id = _client_id(request)
    allowed, retry_after, dimension = request.app["session_admission"].check(client_id)
    if allowed:
        return web.json_response({"ok": True})
    return web.json_response(
        {
            "ok": False,
            "error": f"session {dimension} limit reached",
            "retry_after_s": round(retry_after),
        },
        status=429,
        headers={"Retry-After": str(max(1, round(retry_after)))},
    )


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


async def health_handler(request: web.Request) -> web.Response:
    args = request.app["args"]
    quota = gemini_quota().snapshot()
    return web.json_response(
        {
            "ok": True,
            "mode": args.mode,
            "voice_stack": args.voice_stack,
            "asr": args.asr,
            "tts": args.tts_backend,
            "barge_in": args.barge_in,
            "session_active": active["session"] is not None,
            "gemini_quota": {
                "rpm": {"used": quota.rpm_used, "limit": quota.rpm_limit},
                "rpd": {"used": quota.rpd_used, "limit": quota.rpd_limit},
                "concurrent": {"used": quota.concurrent_used, "limit": quota.concurrent_limit},
            },
        }
    )


async def readiness_handler(request: web.Request) -> web.Response:
    """Configuration readiness; provider reachability is measured by live error metrics."""
    args = request.app["args"]
    missing: list[str] = []
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if (args.asr == "sarvam" or args.tts_backend.startswith("sarvam")) and not os.environ.get("SARVAM_API_KEY"):
        missing.append("SARVAM_API_KEY")
    ready = not missing
    return web.json_response({"ready": ready, "missing": missing}, status=200 if ready else 503)


async def metrics_handler(request: web.Request) -> web.Response:
    return web.Response(text=METRICS.render(), content_type="text/plain")


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
    ap.add_argument(
        "--session-max-seconds",
        type=int,
        default=int(os.environ.get("SESSION_MAX_SECONDS", "240")),
        help="hard server-side session cap; protects provider spend even if the browser is modified",
    )
    ap.add_argument("--voice-stack", choices=["open", "moshi", "none"], default="open",
                    help="open is the reliable local VAD/ASR/TTS cascade; moshi keeps the experimental "
                         "full-duplex model; none runs transcript/capture only")
    ap.add_argument("--no-model", action="store_true",
                     help="deprecated alias for --voice-stack none")
    ap.add_argument("--capture", action="store_true",
                     help="opt-in session recording, ON for every session from server start (off by "
                          "default). The web UI also has a per-session toggle for the same thing.")
    ap.add_argument("--asr-min-rms", type=float, default=float(os.environ.get("ASR_MIN_RMS", "0.003")),
                    help="minimum adaptive speech threshold (old fixed value was 0.015 and rejected quiet voices)")
    default_asr = os.environ.get("ASR_ENGINE", "sarvam" if os.environ.get("SARVAM_API_KEY") else "parakeet")
    default_tts = os.environ.get("TTS_BACKEND", "sarvam-ws" if os.environ.get("SARVAM_API_KEY") else "piper")
    ap.add_argument("--asr", default=default_asr,
                    help="recognizer: sarvam (streaming default when configured), parakeet[:HF repo], or whisper[:model]")
    ap.add_argument("--asr-model", default=None,
                    help="deprecated faster-whisper shortcut; e.g. --asr-model small.en means --asr whisper:small.en")
    ap.add_argument("--vad-threshold", type=float, default=float(os.environ.get("VAD_THRESHOLD", "0.55")),
                    help="Silero speech probability threshold")
    ap.add_argument("--vad-min-speech-ms", type=int, default=int(os.environ.get("VAD_MIN_SPEECH_MS", "160")),
                    help="reject candidate windows with less neural-VAD speech than this")
    ap.add_argument("--turn-grace-ms", type=int, default=int(os.environ.get("TURN_GRACE_MS", "450")),
                    help="merge resumed Sarvam speech segments into one thought within this window")
    ap.add_argument("--barge-in", action="store_true",
                    help="controlled duplex: keep streaming ASR active during TTS and cancel playback "
                         "after a meaningful partial transcript (best with headphones)")
    ap.add_argument("--sarvam-language", default=os.environ.get("SARVAM_LANGUAGE", "en-IN"),
                    help="BCP-47 input/output language for Sarvam speech")
    ap.add_argument("--sarvam-mode", choices=["transcribe", "verbatim", "codemix"],
                    default=os.environ.get("SARVAM_MODE", "transcribe"),
                    help="Saaras v3 output mode")
    ap.add_argument("--sarvam-stt", choices=["realtime", "legacy"],
                    default=os.environ.get("SARVAM_STT", "realtime"),
                    help="realtime has true interim transcripts and immediate VAD events; legacy is fallback")
    ap.add_argument("--sarvam-silence-ms", type=int,
                    default=int(os.environ.get("SARVAM_SILENCE_MS", "450")),
                    help="provider end-of-turn silence in milliseconds (default 450)")
    ap.add_argument("--tts-backend", choices=["sarvam-ws", "sarvam", "piper", "kokoro"], default=default_tts,
                    help="persistent Sarvam WebSocket (recommended), legacy Sarvam HTTP, "
                         "stable local Piper, or experimental local Kokoro")
    args = ap.parse_args()
    args.mode = "sdr"  # internal telemetry label; Duet now has one product runtime
    if args.no_model:
        args.voice_stack = "none"
    if args.asr_model:
        args.asr = f"whisper:{args.asr_model}"
    if args.barge_in and (args.voice_stack != "open" or args.asr != "sarvam"):
        ap.error("--barge-in currently requires --voice-stack open --asr sarvam")
    if args.hf_repo is None and args.voice_stack == "moshi":
        from duet_agent import local_loop  # deferred — see the import note near FRAME above
        args.hf_repo = local_loop.DEFAULT_REPOS[args.quantized]

    app = web.Application()
    app["args"] = args
    app["session_admission"] = SessionAdmission.from_env()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/session-capacity", session_capacity_handler)
    app.router.add_post("/corrections", corrections_handler)
    app.router.add_get("/healthz", health_handler)
    app.router.add_get("/readyz", readiness_handler)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/", lambda r: web.FileResponse(STATIC / "index.html"))
    app.router.add_static("/static", STATIC)
    if args.voice_stack == "open":
        detector = "Sarvam streaming VAD" if args.asr == "sarvam" else "Silero"
        duplex = " + controlled barge-in" if args.barge_in else ""
        voice = f"voice: {detector} + {args.asr} ASR + {args.tts_backend} TTS{duplex}"
    elif args.voice_stack == "none":
        voice = "NO VOICE (ASR/brain/capture only)"
    else:
        voice = f"experimental Moshi: {args.hf_repo}"
    print(f"Duet web demo → http://localhost:{args.port}  (ASBL SDR demo; {voice}, capture default {'ON' if args.capture else 'off'})")
    web.run_app(app, port=args.port, print=None)


if __name__ == "__main__":
    main()
