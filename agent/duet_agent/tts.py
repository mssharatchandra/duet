# Duet — pluggable streaming TTS ("the quality voice tier").
#
# Why this exists: our duplex core (Moshi) has human-like TIMING but a
# mediocre voice; good TTS has the reverse. The hybrid experiment in
# eval/bench/run_bench.py needs a voice it can drive from Moshi's turn-taking
# decisions, so the voice has to be swappable and — critically — STREAMING.
#
# The metric that matters here is TTFB (time to FIRST audio chunk), not total
# synthesis time. In conversation nobody hears your throughput; they hear how
# long the silence was before you started talking. A backend with 2x the RTF
# but half the TTFB is the better conversational voice.
#
# Every backend yields float32 PCM at 24 kHz — Duet's pipeline rate — so no
# resampling happens anywhere downstream (one clock, end to end).
#
# Backends import lazily: a missing optional dependency must never break
# `import duet_agent.tts`, because the hybrid benchmark should still run with
# whatever is installed.

from __future__ import annotations

import base64
import importlib.util
import json
import os
import struct
import sys
import threading
import urllib.request
import wave
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import numpy as np

PIPELINE_RATE = 24_000


def resample(pcm: np.ndarray, src_rate: int, dst_rate: int = PIPELINE_RATE) -> np.ndarray:
    """Linear interpolation. Adequate for speech at these rates; the same
    approach used by the benchmark's caller synthesis."""
    if src_rate == dst_rate:
        return pcm.astype(np.float32)
    n_out = int(len(pcm) * dst_rate / src_rate)
    return np.interp(np.linspace(0, len(pcm) - 1, n_out), np.arange(len(pcm)), pcm).astype(np.float32)


def is_available(module: str) -> bool:
    """Check importability without importing — keeps startup cheap and lets
    callers enumerate backends without paying model-load costs."""
    if module == "stdlib":
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


class StreamingTTS(ABC):
    """A voice. `synthesize_stream` must yield its FIRST chunk as early as the
    backend allows — that latency is the whole point of this abstraction."""

    name = "abstract"
    sample_rate = PIPELINE_RATE

    @abstractmethod
    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        """Yield float32 PCM chunks at PIPELINE_RATE."""

    def synthesize(self, text: str) -> np.ndarray:
        chunks = list(self.synthesize_stream(text))
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


class PiperTTS(StreamingTTS):
    """Baseline: small, fast, always installed here (used by the benchmark's
    simulated caller). Genuinely streaming — Piper yields per-sentence chunks."""

    name = "piper"
    DEFAULT_VOICE = "en/en_US/lessac/medium/en_US-lessac-medium.onnx"

    def __init__(self, voice_path: str | None = None):
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice

        onnx = voice_path or hf_hub_download("rhasspy/piper-voices", self.DEFAULT_VOICE)
        config = hf_hub_download("rhasspy/piper-voices", self.DEFAULT_VOICE + ".json")
        self._voice = PiperVoice.load(onnx, config)
        self._src_rate = self._voice.config.sample_rate

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        for chunk in self._voice.synthesize(text):
            pcm = np.frombuffer(chunk.audio_int16_bytes, np.int16).astype(np.float32) / 32768.0
            yield resample(pcm, self._src_rate)


class KokoroTTS(StreamingTTS):
    """Kokoro-82M (Apache-2.0). Tiny for its quality and CPU-friendly, which
    makes it the interesting candidate for a local-first personal agent."""

    name = "kokoro"

    def __init__(self, voice: str = "af_heart", lang_code: str = "a"):
        from kokoro import KPipeline

        self._pipeline = KPipeline(lang_code=lang_code)
        self._voice = voice
        self._src_rate = 24_000  # Kokoro's native rate happens to match ours

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        for _gs, _ps, audio in self._pipeline(text, voice=self._voice):
            pcm = np.asarray(audio, dtype=np.float32)
            yield resample(pcm, self._src_rate)


class ChatterboxTTS(StreamingTTS):
    """Chatterbox (MIT, resemble-ai). Claims sub-200 ms inference; the most
    likely candidate to beat Moshi's voice while staying real-time. Heavier
    dependency (torch), so it may not install everywhere — that's why every
    backend here is optional."""

    name = "chatterbox"

    def __init__(self, device: str | None = None):
        import torch
        from chatterbox.tts import ChatterboxTTS as _Chatterbox

        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = _Chatterbox.from_pretrained(device=device)
        self._src_rate = self._model.sr

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        # Chatterbox's public API is one-shot; we still expose it through the
        # streaming interface so callers stay uniform. TTFB therefore equals
        # full synthesis time for this backend — reported honestly by the bench.
        wav = self._model.generate(text)
        pcm = np.asarray(wav.squeeze().detach().cpu().numpy(), dtype=np.float32)
        yield resample(pcm, self._src_rate)


class SarvamTTS(StreamingTTS):
    """Sarvam Bulbul v3 streamed as PCM from its chunked WAV response."""

    name = "sarvam"

    def __init__(
        self,
        api_key: str | None = None,
        speaker: str | None = None,
        language_code: str | None = None,
        pace: float | None = None,
        temperature: float | None = None,
    ):
        self.api_key = api_key or os.environ.get("SARVAM_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("SARVAM_API_KEY not set (see .env.example)")
        # v1 used Shubh at pace 1.05 / temperature 0.55.  The provider defines
        # 1.0 as natural pace, so that configuration literally hurried the
        # voice while a low temperature flattened it.  Defaults below favor a
        # calm, warm female concierge and remain environment-overridable.
        self.speaker = speaker or os.environ.get("SARVAM_SPEAKER", "priya")
        self.language_code = language_code or os.environ.get("SARVAM_LANGUAGE", "en-IN")
        self.pace = pace if pace is not None else float(os.environ.get("SARVAM_TTS_PACE", "0.94"))
        self.temperature = (
            temperature if temperature is not None else float(os.environ.get("SARVAM_TTS_TEMPERATURE", "0.72"))
        )
        if not 0.5 <= self.pace <= 2.0:
            raise ValueError("SARVAM_TTS_PACE must be between 0.5 and 2.0")
        if not 0.01 <= self.temperature <= 2.0:
            raise ValueError("SARVAM_TTS_TEMPERATURE must be between 0.01 and 2.0")

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        body = json.dumps(
            {
                "text": text,
                "target_language_code": self.language_code,
                "speaker": self.speaker,
                "pace": self.pace,
                "speech_sample_rate": PIPELINE_RATE,
                "model": "bulbul:v3",
                "temperature": self.temperature,
                "output_audio_codec": "wav",
            }
        ).encode()
        request = urllib.request.Request(
            "https://api.sarvam.ai/text-to-speech/stream",
            data=body,
            headers={"api-subscription-key": self.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            yield from _stream_wav_pcm(response)


class SarvamWebSocketTTS(StreamingTTS):
    """Persistent Bulbul v3 connection for conversational synthesis.

    The HTTP endpoint opens a new network/TLS request for every turn.  This
    backend configures one WebSocket once and reuses it until the session ends.
    If playback is interrupted, closing the generator deliberately discards
    that socket: unread audio from the cancelled sentence must never leak into
    the caller's next turn.
    """

    name = "sarvam-ws"

    def __init__(
        self,
        api_key: str | None = None,
        speaker: str | None = None,
        language_code: str | None = None,
        pace: float | None = None,
    ):
        self.api_key = api_key or os.environ.get("SARVAM_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("SARVAM_API_KEY not set (see .env.example)")
        self.speaker = speaker or os.environ.get("SARVAM_SPEAKER", "simran")
        self.language_code = language_code or os.environ.get("SARVAM_LANGUAGE", "en-IN")
        self.pace = pace if pace is not None else float(os.environ.get("SARVAM_TTS_PACE", "1.04"))
        self.temperature = None  # the current generated WS SDK does not expose this v3 field
        if not 0.5 <= self.pace <= 2.0:
            raise ValueError("SARVAM_TTS_PACE must be between 0.5 and 2.0")
        self._lock = threading.Lock()
        self._connection = None
        self._socket = None
        self._closed = threading.Event()
        self._keepalive_started = False

    def _connect(self):
        if self._socket is not None:
            return self._socket
        from sarvamai import SarvamAI

        client = SarvamAI(api_subscription_key=self.api_key)
        connection = client.text_to_speech_streaming.connect(
            model="bulbul:v3",
            send_completion_event="true",
        )
        socket = connection.__enter__()
        try:
            socket.configure(
                target_language_code=self.language_code,
                speaker=self.speaker,
                pace=self.pace,
                speech_sample_rate=PIPELINE_RATE,
                output_audio_codec="linear16",
                min_buffer_size=50,
                max_chunk_length=120,
            )
        except BaseException:
            connection.__exit__(*sys.exc_info())
            raise
        self._connection = connection
        self._socket = socket
        if not self._keepalive_started:
            self._keepalive_started = True
            threading.Thread(target=self._keepalive_loop, daemon=True).start()
        return socket

    def warm(self) -> None:
        """Pay connection setup before the first caller turn."""
        with self._lock:
            self._connect()

    def _keepalive_loop(self) -> None:
        while not self._closed.wait(20):
            with self._lock:
                if self._socket is None:
                    continue
                try:
                    self._socket.ping()
                except Exception:  # noqa: BLE001 -- any dead provider socket is discarded
                    self._disconnect()

    def _disconnect(self, *, abort: bool = False) -> None:
        connection, self._connection = self._connection, None
        socket, self._socket = self._socket, None
        if abort and socket is not None:
            # A barge-in is a cancellation, not a graceful end-of-session.
            # Waiting for a close handshake can hold the mouth for 10 seconds.
            protocol = getattr(socket, "_websocket", None)
            close_socket = getattr(protocol, "close_socket", None)
            if close_socket is not None:
                try:
                    close_socket()
                except Exception:  # noqa: BLE001, S110 -- best-effort abort during cancellation
                    pass
        if connection is not None:
            try:
                connection.__exit__(None, None, None)
            except Exception:  # noqa: BLE001, S110 -- teardown cannot mask the original failure
                pass

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._disconnect()

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        if not text.strip():
            return
        with self._lock:
            completed = False
            try:
                socket = self._connect()
                socket.convert(text)
                socket.flush()
                while True:
                    message = socket.recv()
                    if message.type == "audio":
                        encoded = message.data.audio
                        pcm = np.frombuffer(base64.b64decode(encoded), np.int16).astype(np.float32) / 32768.0
                        if len(pcm):
                            yield pcm
                    elif message.type == "event" and str(message.data.event_type).lower() == "final":
                        completed = True
                        return
                    elif message.type == "error":
                        raise RuntimeError(f"Sarvam streaming TTS error: {message}")
            finally:
                # Normal completions keep the warm socket. Cancellation or a
                # protocol failure invalidates it so stale audio cannot cross turns.
                if not completed:
                    self._disconnect(abort=True)


BACKENDS: dict[str, tuple[type[StreamingTTS], str]] = {
    "piper": (PiperTTS, "piper"),
    "kokoro": (KokoroTTS, "kokoro"),
    "chatterbox": (ChatterboxTTS, "chatterbox"),
    "sarvam": (SarvamTTS, "stdlib"),
    "sarvam-ws": (SarvamWebSocketTTS, "sarvamai"),
}


def available_backends() -> list[str]:
    return [name for name, (_cls, module) in BACKENDS.items() if is_available(module)]


def load(name: str, **kwargs) -> StreamingTTS:
    if name not in BACKENDS:
        raise ValueError(f"unknown TTS backend {name!r}; known: {sorted(BACKENDS)}")
    cls, module = BACKENDS[name]
    if not is_available(module):
        raise RuntimeError(f"TTS backend {name!r} needs the {module!r} package: uv pip install -e 'agent[tts]'")
    return cls(**kwargs)


def write_wav(path: Path, pcm: np.ndarray, sample_rate: int = PIPELINE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


def iter_pcm_frames(chunks: Iterator[np.ndarray], frame_size: int) -> Iterator[np.ndarray]:
    """Re-chunk a continuous PCM stream without inserting silence between chunks.

    Provider response boundaries have no acoustic meaning.  In particular,
    Sarvam commonly yields 2,048-sample chunks while Duet's browser transport
    uses 1,920-sample frames.  Padding every provider chunk would insert a long
    silent gap after almost every audio frame.  Carry the remainder forward
    and pad only the final transport frame.
    """
    if frame_size <= 0:
        raise ValueError("frame_size must be positive")
    pending = np.zeros(0, dtype=np.float32)
    try:
        for chunk in chunks:
            pcm = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if not len(pcm):
                continue
            if len(pending):
                pcm = np.concatenate((pending, pcm))
            offset = 0
            while len(pcm) - offset >= frame_size:
                yield pcm[offset:offset + frame_size].copy()
                offset += frame_size
            pending = pcm[offset:].copy()
        if len(pending):
            yield np.pad(pending, (0, frame_size - len(pending)))
    finally:
        # Cancellation must reach the provider iterator. Without this, an
        # interrupted WebSocket TTS generator remains suspended while holding
        # its serialization lock, and the next response hangs forever.
        close = getattr(chunks, "close", None)
        if close is not None:
            close()


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ValueError("truncated streaming WAV header")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _stream_wav_pcm(stream, read_size: int = 4096) -> Iterator[np.ndarray]:
    """Yield float32 mono PCM while a PCM WAV response is still arriving."""
    riff = _read_exact(stream, 12)
    if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
        raise ValueError("Sarvam TTS did not return a RIFF/WAVE stream")

    channels = sample_rate = bits = audio_format = None
    while True:
        chunk_id, chunk_size = struct.unpack("<4sI", _read_exact(stream, 8))
        if chunk_id == b"fmt ":
            fmt = _read_exact(stream, chunk_size)
            audio_format, channels, sample_rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
        elif chunk_id == b"data":
            break
        else:
            _read_exact(stream, chunk_size)
        if chunk_size & 1:
            _read_exact(stream, 1)

    if audio_format != 1 or bits != 16 or not channels or not sample_rate:
        raise ValueError(
            f"unsupported streaming WAV format: format={audio_format}, channels={channels}, "
            f"rate={sample_rate}, bits={bits}"
        )

    frame_bytes = channels * 2
    pending = b""
    while True:
        raw = stream.read(read_size)
        if not raw:
            break
        raw = pending + raw
        usable = len(raw) - (len(raw) % frame_bytes)
        pending = raw[usable:]
        if not usable:
            continue
        samples = np.frombuffer(raw[:usable], dtype="<i2").astype(np.float32).reshape(-1, channels)
        pcm = samples.mean(axis=1) / 32768.0
        yield resample(pcm, sample_rate)
