# Tests run without any TTS backend installed: the point of the lazy-import
# design is that `import duet_agent.tts` must never fail, so the tests must not
# require model downloads either.

import base64
import io
import sys
import wave
from types import SimpleNamespace

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


def test_frame_iterator_propagates_cancellation_to_provider():
    closed = []

    def source():
        try:
            while True:
                yield np.ones(2400, np.float32)
        finally:
            closed.append(True)

    frames = tts.iter_pcm_frames(source(), 1920)
    next(frames)
    frames.close()

    assert closed == [True]


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


def test_stream_wav_pcm_yields_incremental_chunks():
    source = (np.sin(np.linspace(0, 8, 2400)) * 12000).astype(np.int16)
    encoded = io.BytesIO()
    with wave.open(encoded, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24_000)
        wav.writeframes(source.tobytes())
    chunks = list(tts._stream_wav_pcm(io.BytesIO(encoded.getvalue()), read_size=511))
    decoded = np.concatenate(chunks)
    assert len(chunks) > 1
    assert len(decoded) == len(source)
    assert np.max(np.abs(decoded - source.astype(np.float32) / 32768.0)) < 1e-6


def test_sarvam_tts_requires_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SARVAM_API_KEY"):
        tts.SarvamTTS()


def test_sarvam_voice_defaults_are_calm_and_environment_overridable(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    voice = tts.SarvamTTS()
    assert voice.speaker == "priya"
    assert voice.pace == pytest.approx(0.94)
    assert voice.temperature == pytest.approx(0.72)

    monkeypatch.setenv("SARVAM_TTS_PACE", "0.88")
    monkeypatch.setenv("SARVAM_TTS_TEMPERATURE", "0.8")
    tuned = tts.SarvamTTS(speaker="ishita")
    assert tuned.speaker == "ishita"
    assert tuned.pace == pytest.approx(0.88)
    assert tuned.temperature == pytest.approx(0.8)


def test_sarvam_websocket_reuses_warm_connection(monkeypatch):
    pcm = np.array([1000, -1000], dtype=np.int16)

    class Socket:
        def __init__(self):
            self.configure_calls = 0
            self.responses = []

        def configure(self, **_kwargs):
            self.configure_calls += 1

        def convert(self, _text):
            self.responses.extend([
                SimpleNamespace(type="audio", data=SimpleNamespace(audio=base64.b64encode(pcm.tobytes()).decode())),
                SimpleNamespace(type="event", data=SimpleNamespace(event_type="final")),
            ])

        def flush(self):
            pass

        def recv(self):
            return self.responses.pop(0)

    socket = Socket()

    class Connection:
        enters = 0

        def __enter__(self):
            self.enters += 1
            return socket

        def __exit__(self, *_args):
            pass

    connection = Connection()
    client = SimpleNamespace(
        text_to_speech_streaming=SimpleNamespace(connect=lambda **_kwargs: connection)
    )
    monkeypatch.setitem(sys.modules, "sarvamai", SimpleNamespace(SarvamAI=lambda **_kwargs: client))
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    voice = tts.SarvamWebSocketTTS()

    first = np.concatenate(list(voice.synthesize_stream("first")))
    second = np.concatenate(list(voice.synthesize_stream("second")))
    voice.close()

    assert connection.enters == 1
    assert socket.configure_calls == 1
    assert first.tolist() == pytest.approx([1000 / 32768, -1000 / 32768])
    assert second.tolist() == pytest.approx(first.tolist())


def test_sarvam_websocket_cancellation_discards_connection(monkeypatch):
    encoded = base64.b64encode(np.ones(20, dtype=np.int16).tobytes()).decode()

    class Socket:
        def configure(self, **_kwargs):
            pass

        def convert(self, _text):
            pass

        def flush(self):
            pass

        def recv(self):
            return SimpleNamespace(type="audio", data=SimpleNamespace(audio=encoded))

    exits = []

    class Connection:
        def __enter__(self):
            return Socket()

        def __exit__(self, *_args):
            exits.append(True)

    client = SimpleNamespace(
        text_to_speech_streaming=SimpleNamespace(connect=lambda **_kwargs: Connection())
    )
    monkeypatch.setitem(sys.modules, "sarvamai", SimpleNamespace(SarvamAI=lambda **_kwargs: client))
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    stream = tts.SarvamWebSocketTTS().synthesize_stream("cancel me")

    next(stream)
    stream.close()

    assert exits == [True]


def test_iter_pcm_frames_carries_provider_remainders_without_internal_silence():
    # This reproduces the live Sarvam mismatch: 2,048-sample HTTP chunks must
    # become 1,920-sample browser frames without padding each HTTP boundary.
    source = np.linspace(-0.75, 0.75, 2_048 * 3, dtype=np.float32)
    provider_chunks = iter(np.split(source, 3))
    frames = list(tts.iter_pcm_frames(provider_chunks, 1_920))
    decoded = np.concatenate(frames)

    assert all(len(frame) == 1_920 for frame in frames)
    assert np.array_equal(decoded[:len(source)], source)
    assert np.count_nonzero(decoded[len(source):]) == 0


def test_iter_pcm_frames_rejects_invalid_frame_size():
    with pytest.raises(ValueError, match="positive"):
        list(tts.iter_pcm_frames(iter([np.ones(3, np.float32)]), 0))
