import numpy as np
import pytest

from duet_agent import asr


def test_meaningful_text_rejects_silence_artifacts():
    assert not asr.meaningful_text(". . . . .")
    assert not asr.meaningful_text("thanks thanks thanks thanks")
    assert asr.meaningful_text("Hello")
    assert asr.meaningful_text("That is the authorization server")


def test_resample_preserves_duration():
    pcm = np.linspace(-1, 1, 24_000, dtype=np.float32)
    out = asr._resample(pcm, 24_000, 16_000)
    assert out.dtype == np.float32
    assert len(out) == 16_000


def test_load_asr_rejects_unknown_backend():
    with pytest.raises(ValueError, match="parakeet"):
        asr.load_asr("made-up")
