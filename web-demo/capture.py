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
# Live ASR and capture both use UtteranceSegmenter below. They receive the identical frame stream,
# so both instances close an utterance on the same frame; server.py can pair the captured WAV with
# the hypothesis produced for it without separate alignment bookkeeping.

from __future__ import annotations

import json
import time
import uuid
import wave
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

SAMPLE_RATE = 24_000
FRAME_SIZE = 1_920  # 1920 samples / 24 kHz = 80 ms. Duplicated from duet_agent.local_loop.FRAME_SIZE
                     # rather than imported — importing local_loop pulls in mlx/moshi_mlx, which this
                     # module is not allowed to depend on (see header). Frame size is a stable contract,
                     # not an implementation detail, so the duplication is deliberate, not drift risk.

# A fixed 0.015 gate discarded most real laptop-mic speech before Whisper ever saw it: one verified
# session had median frame RMS 0.00396 and only 5/14 frames crossed the old threshold. The adaptive
# gate estimates the room floor from recent inactive frames and asks for a modest signal-over-noise
# margin, while a minimum prevents a near-silent room from triggering on numerical noise.
MIN_RMS_THRESHOLD = 0.003
NOISE_MULTIPLIER = 1.8
NOISE_WINDOW_FRAMES = 125  # 10 seconds at 80 ms/frame
PRE_ROLL_FRAMES = 0        # real short-utterance replay: room-tone prefix caused Whisper hallucinations
CALIBRATION_FRAMES = 6     # estimate 480 ms of room tone before accepting speech
VOICED_FRAMES_TO_COUNT = 2 # accept short answers such as "yes" (~160 ms)
QUIET_FRAMES_TO_END = 8


@dataclass
class UtteranceRecord:
    utterance_id: str
    wav_path: str
    asr_hypothesis: str
    ground_truth: str | None
    duration_s: float
    timestamp: float


class UtteranceSegmenter:
    """Adaptive energy segmenter shared by live ASR and opt-in capture.

    This is intentionally not called semantic turn detection. It only fixes the
    acoustic bug where quiet speech never reached ASR; hesitations and semantic
    completion still need a real end-of-turn model.
    """

    def __init__(
        self,
        min_rms_threshold: float = MIN_RMS_THRESHOLD,
        noise_multiplier: float = NOISE_MULTIPLIER,
        voiced_frames_to_count: int = VOICED_FRAMES_TO_COUNT,
        quiet_frames_to_end: int = QUIET_FRAMES_TO_END,
        pre_roll_frames: int = PRE_ROLL_FRAMES,
        calibration_frames: int = CALIBRATION_FRAMES,
    ):
        self.min_rms_threshold = min_rms_threshold
        self.noise_multiplier = noise_multiplier
        self.voiced_frames_to_count = voiced_frames_to_count
        self.quiet_frames_to_end = quiet_frames_to_end
        self.calibration_frames = calibration_frames
        self._noise_rms: deque[float] = deque(maxlen=NOISE_WINDOW_FRAMES)
        self._pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_frames)
        self._buf: list[np.ndarray] = []
        self.voiced_frames = 0
        self.quiet_frames = 0
        self.active = False
        self.last_rms = 0.0

    @property
    def noise_floor(self) -> float:
        if not self._noise_rms:
            return self.min_rms_threshold / self.noise_multiplier
        # The low quartile stays representative even when the inactive window
        # contains a few speech onsets or keyboard taps.
        return float(np.percentile(np.fromiter(self._noise_rms, dtype=np.float32), 25))

    @property
    def threshold(self) -> float:
        return max(self.min_rms_threshold, self.noise_floor * self.noise_multiplier)

    @property
    def calibrating(self) -> bool:
        return not self.active and len(self._noise_rms) < self.calibration_frames

    def add_frame(self, pcm: np.ndarray) -> np.ndarray | None:
        if pcm.shape != (FRAME_SIZE,):
            raise ValueError(f"expected one {FRAME_SIZE}-sample frame, got shape {pcm.shape}")
        self.last_rms = float(np.sqrt(np.mean(np.square(pcm))))
        if self.calibrating:
            self._noise_rms.append(self.last_rms)
            self._pre_roll.append(pcm.copy())
            return None
        is_voiced = self.last_rms >= self.threshold

        if not self.active:
            if not is_voiced:
                self._noise_rms.append(self.last_rms)
                self._pre_roll.append(pcm.copy())
                return None
            self.active = True
            self._buf = [*self._pre_roll, pcm.copy()]
            self._pre_roll.clear()
            self.voiced_frames = 1
            self.quiet_frames = 0
            return None

        self._buf.append(pcm.copy())
        if is_voiced:
            self.voiced_frames += 1
            self.quiet_frames = 0
            return None

        self.quiet_frames += 1
        if self.quiet_frames < self.quiet_frames_to_end:
            return None

        audio = np.concatenate(self._buf) if self.voiced_frames >= self.voiced_frames_to_count else None
        # Reuse the tail silence as pre-roll/noise evidence for the next onset.
        tail = self._buf[-self._pre_roll.maxlen:] if self._pre_roll.maxlen else []
        for frame in tail:
            rms = float(np.sqrt(np.mean(np.square(frame))))
            self._noise_rms.append(rms)
            self._pre_roll.append(frame)
        self._buf = []
        self.voiced_frames = 0
        self.quiet_frames = 0
        self.active = False
        return audio


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
        min_rms_threshold: float = MIN_RMS_THRESHOLD,
        noise_multiplier: float = NOISE_MULTIPLIER,
        voiced_frames_to_count: int = VOICED_FRAMES_TO_COUNT,
        quiet_frames_to_end: int = QUIET_FRAMES_TO_END,
        calibration_frames: int = CALIBRATION_FRAMES,
        now: Callable[[], float] | None = None,
    ):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.session_dir / "utterances.jsonl"
        self._sample_rate = sample_rate
        self.segmenter = UtteranceSegmenter(
            min_rms_threshold=min_rms_threshold,
            noise_multiplier=noise_multiplier,
            voiced_frames_to_count=voiced_frames_to_count,
            quiet_frames_to_end=quiet_frames_to_end,
            calibration_frames=calibration_frames,
        )
        self._now = now or time.time
        # In-memory index so set_hypothesis()/apply_correction() can patch a row without
        # re-parsing the file. Sessions are short (a demo call, not a call center), so this
        # stays small; if that stops being true, switch to an on-disk index first.
        self.records: dict[str, UtteranceRecord] = {}
        self._order: list[str] = []

    def add_frame(self, pcm: np.ndarray) -> UtteranceRecord | None:
        audio = self.segmenter.add_frame(pcm)
        return self._flush(audio) if audio is not None else None

    def _flush(self, audio: np.ndarray) -> UtteranceRecord:
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
