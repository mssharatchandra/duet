# Unit tests for web-demo/capture.py's SessionCapture — the opt-in ASR-eval recorder (see
# docs/DECISIONS.md 0009/0012). capture.py is deliberately outside the duet_agent package (no
# aiohttp/Moshi imports allowed there — see its header), so it's reached the same way server.py
# reaches it: web-demo/ is a plain sys.path addition, not an installed package.

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web-demo"))

from capture import FRAME_SIZE, SessionCapture, UtteranceSegmenter  # noqa: E402

LOUD = np.full(FRAME_SIZE, 0.1, dtype=np.float32)   # rms 0.1 > any adaptive threshold in these tests
QUIET = np.zeros(FRAME_SIZE, dtype=np.float32)       # rms 0.0 < threshold


def make(tmp_path, **kw) -> SessionCapture:
    t = {"now": 1000.0}
    return SessionCapture(tmp_path / "sess", now=lambda: t["now"], calibration_frames=0, **kw), t


def feed(cap: SessionCapture, frame: np.ndarray, n: int):
    """Push `frame` n times, returning the last (possibly non-None) return value."""
    last = None
    for _ in range(n):
        last = cap.add_frame(frame)
    return last


# -- segmentation boundaries -------------------------------------------------


def test_no_flush_while_only_voiced(tmp_path):
    cap, _ = make(tmp_path)
    for _ in range(10):
        assert cap.add_frame(LOUD) is None
    assert cap.records == {}


def test_short_blip_does_not_count_as_an_utterance(tmp_path):
    """One 80 ms impulse is discarded while two frames allow short answers such as "yes"."""
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 1)
    record = feed(cap, QUIET, 8)          # enough quiet to close the window
    assert record is None
    assert cap.records == {}
    assert not (tmp_path / "sess").exists() or list((tmp_path / "sess").glob("*.wav")) == []


def test_utterance_flushes_after_voiced_then_quiet(tmp_path):
    """>=0.16s speech (2 frames) then >=0.6s silence (8 frames) closes exactly one utterance,
    on the exact frame that crosses the quiet threshold — not before, not after."""
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    for i in range(1, 8):
        assert cap.add_frame(QUIET) is None, f"should not flush before 8 quiet frames (at {i})"
    record = cap.add_frame(QUIET)         # 8th quiet frame — boundary
    assert record is not None
    assert record.utterance_id in cap.records
    # 5 voiced + 8 quiet frames of 80 ms each = 1.04 s of audio in the WAV
    assert record.duration_s == pytest.approx((5 + 8) * FRAME_SIZE / 24_000, abs=1e-3)


def test_adaptive_gate_detects_quiet_speech_above_room_floor():
    seg = UtteranceSegmenter(calibration_frames=6)
    room = np.full(FRAME_SIZE, 0.002, dtype=np.float32)
    quiet_speech = np.full(FRAME_SIZE, 0.006, dtype=np.float32)
    feed(seg, room, 10)
    assert seg.threshold == pytest.approx(0.0036, abs=1e-4)
    feed(seg, quiet_speech, 3)
    audio = feed(seg, room, 8)
    assert audio is not None
    assert len(audio) == (3 + 8) * FRAME_SIZE


def test_calibration_prevents_constant_room_noise_from_becoming_speech():
    seg = UtteranceSegmenter(calibration_frames=6)
    room = np.full(FRAME_SIZE, 0.006, dtype=np.float32)
    assert feed(seg, room, 20) is None
    assert not seg.active
    assert seg.threshold == pytest.approx(0.0108, abs=1e-4)


def test_quiet_with_empty_buffer_is_a_pure_noop(tmp_path):
    cap, _ = make(tmp_path)
    for _ in range(20):
        assert cap.add_frame(QUIET) is None
    assert cap.records == {}


def test_rejects_wrong_shaped_frame(tmp_path):
    cap, _ = make(tmp_path)
    with pytest.raises(ValueError):
        cap.add_frame(np.zeros(100, dtype=np.float32))


# -- file writing -------------------------------------------------------------


def test_wav_and_jsonl_written_with_correct_fields(tmp_path):
    cap, t = make(tmp_path)
    t["now"] = 12345.0
    feed(cap, LOUD, 5)
    record = feed(cap, QUIET, 8)
    assert record is not None

    wav_path = Path(record.wav_path)
    assert wav_path.exists()
    assert wav_path.suffix == ".wav"

    jsonl_path = tmp_path / "sess" / "utterances.jsonl"
    assert jsonl_path.exists()
    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert set(row) == {"utterance_id", "wav_path", "asr_hypothesis", "ground_truth", "duration_s", "timestamp"}
    assert row["utterance_id"] == record.utterance_id
    assert row["wav_path"] == record.wav_path
    assert row["asr_hypothesis"] == ""
    assert row["ground_truth"] is None
    assert row["timestamp"] == 12345.0


def test_wav_is_16bit_mono_at_24khz(tmp_path):
    import wave

    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    record = feed(cap, QUIET, 8)
    with wave.open(record.wav_path, "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2  # 16-bit
        assert w.getframerate() == 24_000
        assert w.getnframes() == 13 * FRAME_SIZE  # 5 loud + 8 quiet frames concatenated


def test_second_utterance_gets_its_own_file_and_appends_jsonl(tmp_path):
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    first = feed(cap, QUIET, 8)
    feed(cap, LOUD, 5)
    second = feed(cap, QUIET, 8)

    assert first.utterance_id != second.utterance_id
    assert Path(first.wav_path) != Path(second.wav_path)
    lines = (tmp_path / "sess" / "utterances.jsonl").read_text().splitlines()
    assert len(lines) == 2


# -- set_hypothesis ------------------------------------------------------------


def test_set_hypothesis_attaches_text_to_the_right_record(tmp_path):
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    first = feed(cap, QUIET, 8)
    feed(cap, LOUD, 5)
    second = feed(cap, QUIET, 8)

    cap.set_hypothesis(second.utterance_id, "hello there")

    assert cap.records[second.utterance_id].asr_hypothesis == "hello there"
    assert cap.records[first.utterance_id].asr_hypothesis == ""  # untouched

    rows = [json.loads(line) for line in (tmp_path / "sess" / "utterances.jsonl").read_text().splitlines()]
    by_id = {r["utterance_id"]: r for r in rows}
    assert by_id[second.utterance_id]["asr_hypothesis"] == "hello there"
    assert by_id[first.utterance_id]["asr_hypothesis"] == ""


def test_set_hypothesis_on_unknown_id_is_a_silent_noop(tmp_path):
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    feed(cap, QUIET, 8)
    cap.set_hypothesis("does-not-exist", "should not crash")  # must not raise


# -- apply_correction -----------------------------------------------------------


def test_apply_correction_fills_ground_truth(tmp_path):
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    record = feed(cap, QUIET, 8)
    cap.set_hypothesis(record.utterance_id, "helo there")

    ok = cap.apply_correction(record.utterance_id, "hello there")

    assert ok is True
    assert cap.records[record.utterance_id].ground_truth == "hello there"
    row = json.loads((tmp_path / "sess" / "utterances.jsonl").read_text().splitlines()[0])
    assert row["ground_truth"] == "hello there"
    assert row["asr_hypothesis"] == "helo there"  # correction doesn't clobber the original hypothesis


def test_apply_correction_returns_false_for_unknown_id(tmp_path):
    cap, _ = make(tmp_path)
    feed(cap, LOUD, 5)
    feed(cap, QUIET, 8)
    before = (tmp_path / "sess" / "utterances.jsonl").read_text()

    ok = cap.apply_correction("nonexistent-id", "some text")

    assert ok is False
    after = (tmp_path / "sess" / "utterances.jsonl").read_text()
    assert before == after  # file untouched on an unknown id
