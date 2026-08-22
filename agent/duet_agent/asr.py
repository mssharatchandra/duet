"""Pluggable local speech recognition and speech validation for Duet.

The live app used to instantiate faster-whisper directly.  That made the most
important boundary -- whether an audio window contains human speech at all --
an accidental side effect of an RMS threshold.  Whisper will happily complete
noise into plausible language, so this module keeps the two decisions separate:
Silero decides whether speech exists; the selected recognizer transcribes it.
"""

from __future__ import annotations

import importlib.util
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from .asr_util import to_whisper_rate

PIPELINE_RATE = 24_000
DEFAULT_PARAKEET_REPO = "mlx-community/parakeet-tdt-0.6b-v3"


@dataclass(frozen=True)
class Transcript:
    text: str
    latency_ms: float


class LocalASR(ABC):
    name = "abstract"

    @abstractmethod
    def transcribe(self, pcm24k: np.ndarray) -> Transcript:
        """Transcribe one speech-validated float32 utterance at 24 kHz."""


class ParakeetMlxASR(LocalASR):
    """NVIDIA Parakeet TDT through MLX, fed PCM without an ffmpeg subprocess."""

    name = "parakeet-mlx"

    def __init__(self, repo: str = DEFAULT_PARAKEET_REPO):
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel

        self._mx = mx
        self._get_logmel = get_logmel
        self._model = from_pretrained(repo)
        self.repo = repo
        # Compile the lazy MLX graph before the first live utterance.
        self.transcribe(np.zeros(PIPELINE_RATE, dtype=np.float32))

    def transcribe(self, pcm24k: np.ndarray) -> Transcript:
        sr = self._model.preprocessor_config.sample_rate
        audio = _resample(pcm24k, PIPELINE_RATE, sr)
        started = time.perf_counter()
        mel = self._get_logmel(self._mx.array(audio), self._model.preprocessor_config)
        result = self._model.generate(mel)[0]
        return Transcript(text=result.text.strip(), latency_ms=(time.perf_counter() - started) * 1e3)


class FasterWhisperASR(LocalASR):
    """Compatibility fallback; neural VAD still runs before Whisper."""

    name = "faster-whisper"

    def __init__(self, model: str = "small.en"):
        from faster_whisper import WhisperModel

        self.model = model
        self._model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, pcm24k: np.ndarray) -> Transcript:
        started = time.perf_counter()
        segments, _ = self._model.transcribe(
            to_whisper_rate(pcm24k),
            language="en",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return Transcript(text=text, latency_ms=(time.perf_counter() - started) * 1e3)


class SileroSpeechDetector:
    """Neural speech/no-speech check over an already segmented candidate window."""

    name = "silero-vad"

    def __init__(self, threshold: float = 0.55, min_speech_ms: int = 160):
        from silero_vad import get_speech_timestamps, load_silero_vad

        self.threshold = threshold
        self.min_speech_ms = min_speech_ms
        self._timestamps = get_speech_timestamps
        self._model = load_silero_vad(onnx=True)

    def speech_ms(self, pcm24k: np.ndarray) -> int:
        audio16 = to_whisper_rate(pcm24k)
        spans = self._timestamps(
            audio16,
            self._model,
            sampling_rate=16_000,
            threshold=self.threshold,
            min_speech_duration_ms=self.min_speech_ms,
            min_silence_duration_ms=100,
        )
        return round(sum(span["end"] - span["start"] for span in spans) * 1000 / 16_000)

    def contains_speech(self, pcm24k: np.ndarray) -> bool:
        return self.speech_ms(pcm24k) >= self.min_speech_ms


def load_asr(spec: str) -> LocalASR:
    """Load ``parakeet[:repo]`` or ``whisper[:model]``."""
    kind, _, value = spec.partition(":")
    if kind == "parakeet":
        return ParakeetMlxASR(value or DEFAULT_PARAKEET_REPO)
    if kind == "whisper":
        return FasterWhisperASR(value or "small.en")
    raise ValueError("ASR must be parakeet[:repo] or whisper[:model]")


def open_voice_available() -> tuple[bool, list[str]]:
    required = ["parakeet_mlx", "silero_vad", "kokoro"]
    missing = [module for module in required if importlib.util.find_spec(module) is None]
    return not missing, missing


def meaningful_text(text: str) -> bool:
    """Reject punctuation-only output and degenerate repeated-token completions."""
    words = re.findall(r"[\w']+", text.casefold())
    if not words:
        return False
    return not (len(words) >= 4 and len(set(words)) == 1)


def _resample(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return np.asarray(pcm, dtype=np.float32)
    if len(pcm) == 0:
        return np.zeros(0, dtype=np.float32)
    size = max(round(len(pcm) * dst_rate / src_rate), 1)
    return np.interp(np.linspace(0, len(pcm) - 1, size), np.arange(len(pcm)), pcm).astype(np.float32)
