# Duet web demo — opt-in session capture, for building an ON-DISTRIBUTION ASR eval set.
#
# Why this exists (see docs/DECISIONS.md 0009, 0012): eval/asr/run_asr_eval.py measures WER only
# against clean Piper-synthesized speech and gets ~2.3% regardless of model — the eval itself
# proved that number can't explain the "transcription is inaccurate" complaint about a real live
# session (real mic, real room noise, real hesitations/accents). The fix isn't a better synthetic
# eval; it's recorded ground truth from a real session. This module is that recorder.
#
# Kept PURE on purpose: no aiohttp, no Moshi/mlx/rustymimi imports. That's what makes it
# testable without a server or a GPU (agent/tests/test_capture.py) and importable from
# server.py's --no-model path without dragging the model stack in behind it.
#
# Segmentation mirrors server.py's Session._brain_loop EXACTLY — same thresholds, same 1920-
# sample/80ms frame contract: >=0.3s of voiced audio (4 frames) then >=0.6s of quiet (8 frames)
# closes an utterance. server.py feeds this class the identical frame stream, in the identical
# order, that its own inline segmenter sees — so the two state machines close an utterance on the
# exact same frame, which is how server.py pairs a captured utterance with the ASR hypothesis text
# the brain loop produced for it (SessionCapture.add_frame() returns the closed record with an
# empty asr_hypothesis; server.py fills it in via set_hypothesis() once faster-whisper returns).

from __future__ import annotations

import json
import time
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

SAMPLE_RATE = 24_000
FRAME_SIZE = 1_920  # 1920 samples / 24 kHz = 80 ms. Duplicated from duet_agent.local_loop.FRAME_SIZE
                     # rather than imported — importing local_loop pulls in mlx/moshi_mlx, which this
                     # module is not allowed to depend on (see header). Frame size is a stable contract,
                     # not an implementation detail, so the duplication is deliberate, not drift risk.

# Same numbers, same reasoning, as Session._brain_loop in server.py: >=0.3s of speech (4 frames of
# 80ms) then >=0.6s of silence (8 frames) closes an utterance. Keep these in sync with server.py if
# either changes — that's the one place true duplication would silently desync the two segmenters.
VOICED_RMS_THRESHOLD = 0.015
VOICED_FRAMES_TO_COUNT = 4
QUIET_FRAMES_TO_END = 8


@dataclass
class UtteranceRecord:
    utterance_id: str
    wav_path: str
    asr_hypothesis: str
    ground_truth: str | None
    duration_s: float
    timestamp: float


class SessionCapture:
    """Segments a stream of mic frames into utterances; writes each as 16-bit WAV + a JSONL row.

    Frame-driven: call add_frame() once per 1920-sample float32 PCM frame, in order, for EVERY
    frame (voiced or silent) — silence is what lets the segmenter detect the end of an utterance,
    so skipping quiet frames breaks segmentation. Returns the closed UtteranceRecord exactly on
    the frame that ends an utterance, else None.
    """

    def __init__(
        self,
        session_dir: Path | str,
        sample_rate: int = SAMPLE_RATE,
        voiced_rms_threshold: float = VOICED_RMS_THRESHOLD,
        voiced_frames_to_count: int = VOICED_FRAMES_TO_COUNT,
        quiet_frames_to_end: int = QUIET_FRAMES_TO_END,
        now: Callable[[], float] | None = None,
    ):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.session_dir / "utterances.jsonl"
        self._sample_rate = sample_rate
        self._rms_threshold = voiced_rms_threshold
        self._voiced_needed = voiced_frames_to_count
        self._quiet_needed = quiet_frames_to_end
        self._now = now or time.time

        self._buf: list[np.ndarray] = []
        self._voiced = 0
        self._quiet = 0
        # In-memory index so set_hypothesis()/apply_correction() can patch a row without
        # re-parsing the file. Sessions are short (a demo call, not a call center), so this
        # stays small; if that stops being true, switch to an on-disk index first.
        self.records: dict[str, UtteranceRecord] = {}
        self._order: list[str] = []

    def add_frame(self, pcm: np.ndarray) -> UtteranceRecord | None:
        if pcm.shape != (FRAME_SIZE,):
            raise ValueError(f"expected one {FRAME_SIZE}-sample frame, got shape {pcm.shape}")
        rms = float(np.sqrt(np.mean(np.square(pcm))))
        if rms > self._rms_threshold:
            self._voiced += 1
            self._quiet = 0
            self._buf.append(pcm.copy())
            return None
        if not self._buf:
            return None  # quiet with nothing buffered yet — not inside an utterance
        self._quiet += 1
        self._buf.append(pcm.copy())
        if self._quiet >= self._quiet_needed and self._voiced >= self._voiced_needed:
            return self._flush()
        if self._quiet >= self._quiet_needed:
            self._buf, self._voiced, self._quiet = [], 0, 0  # too short to count as speech — discard
        return None

    def _flush(self) -> UtteranceRecord:
        audio = np.concatenate(self._buf)
        self._buf, self._voiced, self._quiet = [], 0, 0
        utterance_id = uuid.uuid4().hex[:12]
        wav_path = self.session_dir / f"{utterance_id}.wav"
        _write_wav(wav_path, audio, self._sample_rate)
        record = UtteranceRecord(
            utterance_id=utterance_id,
            wav_path=str(wav_path),
            asr_hypothesis="",
            ground_truth=None,
            duration_s=round(len(audio) / self._sample_rate, 3),
            timestamp=self._now(),
        )
        self.records[utterance_id] = record
        self._order.append(utterance_id)
        self._append_jsonl(record)
        return record

    def set_hypothesis(self, utterance_id: str, text: str) -> None:
        """Attach the ASR hypothesis the brain loop produced for this utterance."""
        record = self.records.get(utterance_id)
        if record is None:
            return  # unknown id (e.g. a different session) — no-op rather than crash the brain loop
        record.asr_hypothesis = text
        self._rewrite_jsonl()

    def apply_correction(self, utterance_id: str, ground_truth: str) -> bool:
        """Fill in the human-corrected ground truth for one utterance.

        Returns False (file untouched) for an unknown id so the caller (the /corrections HTTP
        route) can surface a real error to the user instead of silently pretending it saved.
        """
        record = self.records.get(utterance_id)
        if record is None:
            return False
        record.ground_truth = ground_truth
        self._rewrite_jsonl()
        return True

    def _append_jsonl(self, record: UtteranceRecord) -> None:
        with self.jsonl_path.open("a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def _rewrite_jsonl(self) -> None:
        # Rewriting the whole file on every update is O(utterances-in-session), not O(1) — fine
        # at demo-session scale (tens of rows) and it means a correction can never corrupt the
        # file by seeking to a stale byte offset. Revisit if sessions get long.
        with self.jsonl_path.open("w") as f:
            for uid in self._order:
                f.write(json.dumps(asdict(self.records[uid])) + "\n")


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """float32 PCM in [-1, 1] -> 16-bit WAV. Clips defensively — live mic audio can exceed 1.0."""
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16.tobytes())
