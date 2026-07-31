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

import importlib.util
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


BACKENDS: dict[str, tuple[type[StreamingTTS], str]] = {
    "piper": (PiperTTS, "piper"),
    "kokoro": (KokoroTTS, "kokoro"),
    "chatterbox": (ChatterboxTTS, "chatterbox"),
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
