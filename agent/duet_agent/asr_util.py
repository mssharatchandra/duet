# Shared ASR input helper.

import numpy as np

WHISPER_RATE = 16_000
PIPELINE_RATE = 24_000


def to_whisper_rate(pcm: np.ndarray) -> np.ndarray:
    """faster-whisper assumes 16 kHz for raw numpy input; our pipeline is 24 kHz.
    Feeding 24 kHz unresampled makes it hear everything slowed 1.5x. It is a
    correctness bug, but later evaluation disproved the claim that it alone was
    the root cause of bad live transcripts (DECISIONS 0012/0015). Linear
    interpolation is adequate for speech at these rates."""
    n = len(pcm)
    m = round(n * WHISPER_RATE / PIPELINE_RATE)
    return np.interp(np.linspace(0, n - 1, m), np.arange(n), pcm).astype(np.float32)
