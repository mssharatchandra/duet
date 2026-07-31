# Tests run without any TTS backend installed: the point of the lazy-import
# design is that `import duet_agent.tts` must never fail, so the tests must not
# require model downloads either.

import numpy as np
import pytest

from duet_agent import tts


class FakeTTS(tts.StreamingTTS):
    """Exercises the StreamingTTS contract without a model."""

    name = "fake"

    def synthesize_stream(self, text):
        for word in text.split():
            yield np.full(1200, 0.1 * len(word), np.float32)


def test_resample_changes_length_proportionally():
    pcm = np.linspace(-1, 1, 22050, dtype=np.float32)
    out = tts.resample(pcm, 22050, 24000)
    assert abs(len(out) - 24000) <= 1
    assert out.dtype == np.float32


def test_resample_is_identity_at_matching_rate():
    pcm = np.linspace(-1, 1, 100, dtype=np.float32)
    assert np.array_equal(tts.resample(pcm, 24000, 24000), pcm)


def test_synthesize_concatenates_stream():
    voice = FakeTTS()
    chunks = list(voice.synthesize_stream("one two three"))
    assert len(chunks) == 3
    assert len(voice.synthesize("one two three")) == 3600


def test_synthesize_handles_empty_text():
    assert len(FakeTTS().synthesize("")) == 0


def test_unknown_backend_raises_with_helpful_message():
    with pytest.raises(ValueError, match="unknown TTS backend"):
        tts.load("does-not-exist")


def test_missing_dependency_raises_actionable_error(monkeypatch):
    """A missing optional dep must produce install guidance, not ImportError."""
    monkeypatch.setattr(tts, "is_available", lambda module: False)
    with pytest.raises(RuntimeError, match="uv pip install"):
        tts.load("kokoro")


def test_available_backends_is_a_subset_of_known():
    assert set(tts.available_backends()) <= set(tts.BACKENDS)


def test_write_wav_roundtrip(tmp_path):
    import wave

    pcm = np.sin(np.linspace(0, 20, 2400)).astype(np.float32)
    path = tmp_path / "s" / "out.wav"
    tts.write_wav(path, pcm)
    with wave.open(str(path)) as w:
        assert w.getframerate() == 24000
        assert w.getnframes() == 2400
        assert w.getnchannels() == 1


def test_write_wav_clips_out_of_range_samples(tmp_path):
    """Values beyond [-1, 1] must clip rather than wrap into loud garbage."""
    import wave

    path = tmp_path / "clip.wav"
    tts.write_wav(path, np.array([5.0, -5.0], np.float32))
    with wave.open(str(path)) as w:
        samples = np.frombuffer(w.readframes(2), np.int16)
    assert samples.tolist() == [32767, -32767]
