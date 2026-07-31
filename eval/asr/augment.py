# Duet — deterministic audio degradations for the ASR discrimination eval.
#
# WHY THIS EXISTS: DECISIONS 0012 found every faster-whisper candidate at ~2.3% WER
# on clean Piper TTS audio — a ceiling too low to distinguish models, and clean TTS
# is not what the live agent actually hears (room noise, mic gain, reverb). These
# functions push synthetic audio closer to a real-room proxy so the eval can
# discriminate. Every function here is PURE: same inputs (including seed) -> same
# output, no hidden state, no wall-clock/randomness leaks. That's what makes the
# eval reproducible and testable.
#
# All functions operate on float32 PCM in [-1, 1] at the caller's sample rate
# (Duet's pipeline rate is 24kHz; see asr_util.PIPELINE_RATE). None of them know
# about Whisper — resampling to 16kHz for faster-whisper is still asr_util's job.

from __future__ import annotations

import numpy as np

CONDITIONS = ("clean", "snr20", "snr10", "snr5", "reverb", "fast", "slow", "clip")


def add_white_noise(pcm: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """Additive Gaussian white noise at a target SNR (dB), measured against the
    signal's own power. Deterministic given `seed`."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(pcm)).astype(np.float32)
    return _mix_at_snr(pcm, noise, snr_db)


def add_pink_noise(pcm: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """Additive pink (1/f) noise at a target SNR (dB) — a closer proxy for HVAC/
    room hiss than white noise. Built by shaping white noise's spectrum with an
    FFT filter, so it stays deterministic given `seed`."""
    rng = np.random.default_rng(seed)
    n = len(pcm)
    white = rng.standard_normal(n).astype(np.float32)
    pink = _pink_from_white(white)
    return _mix_at_snr(pcm, pink, snr_db)


def _pink_from_white(white: np.ndarray) -> np.ndarray:
    n = len(white)
    if n < 2:
        return white.copy()
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs = freqs.copy()
    freqs[0] = freqs[1] if n > 1 else 1.0  # avoid a divide-by-zero at DC
    spectrum = spectrum / np.sqrt(freqs)
    pink = np.fft.irfft(spectrum, n).astype(np.float32)
    std = np.std(pink)
    if std > 1e-12:
        pink = pink / std
    return pink.astype(np.float32)


def _mix_at_snr(signal: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Scale `noise` so signal-to-noise power ratio equals `snr_db`, then add."""
    sig_power = float(np.mean(signal.astype(np.float64) ** 2))
    noise_power = float(np.mean(noise.astype(np.float64) ** 2))
    if sig_power <= 0.0 or noise_power <= 0.0:
        return signal.astype(np.float32).copy()
    target_noise_power = sig_power / (10.0 ** (snr_db / 10.0))
    scale = np.sqrt(target_noise_power / noise_power)
    return (signal + noise * scale).astype(np.float32)


def add_reverb(pcm: np.ndarray, sample_rate: int = 24_000, rt60_s: float = 0.3, wet: float = 0.25, seed: int = 0) -> np.ndarray:
    """Convolve with a synthetic room impulse response: a direct-path spike
    followed by exponentially-decaying random reflections (RT60 = time to decay
    60dB, the standard acoustics definition). Not a measured IR, but far closer
    to a real room than dry TTS. Deterministic given `seed`; output is peak-
    normalized to avoid introducing clipping as a side effect (clipping is its
    own, separate degradation below)."""
    rng = np.random.default_rng(seed)
    ir_len = max(int(round(rt60_s * sample_rate)), 2)
    t = np.arange(ir_len)
    tau = rt60_s * sample_rate / np.log(1000.0)  # exp(-t/tau) hits -60dB at t=rt60
    envelope = np.exp(-t / tau)
    ir = (rng.standard_normal(ir_len).astype(np.float64) * envelope).astype(np.float64)
    ir[0] = 1.0  # direct path dominates
    energy = np.sqrt(np.sum(ir**2))
    if energy > 0:
        ir = ir / energy
    wet_signal = np.convolve(pcm.astype(np.float64), ir, mode="full")[: len(pcm)]
    out = (1.0 - wet) * pcm.astype(np.float64) + wet * wet_signal
    peak = np.max(np.abs(out)) if len(out) else 0.0
    if peak > 1.0:
        out = out / peak
    return out.astype(np.float32)


def change_speed(pcm: np.ndarray, factor: float) -> np.ndarray:
    """Speed perturbation via resampling (Kaldi-style): factor > 1 speeds up and
    shortens the clip, factor < 1 slows it down and lengthens it. This changes
    pitch along with tempo, same as a real device with a slightly-off sample
    clock or a speaker talking faster/slower. Purely deterministic (no RNG)."""
    if factor <= 0:
        raise ValueError("speed factor must be positive")
    n = len(pcm)
    if n < 2:
        return pcm.astype(np.float32).copy()
    m = max(int(round(n / factor)), 1)
    return np.interp(np.linspace(0, n - 1, m), np.arange(n), pcm).astype(np.float32)


def gain_and_clip(pcm: np.ndarray, gain_db: float = 12.0, threshold: float = 1.0) -> np.ndarray:
    """Apply a gain boost (dB) then hard-clip to +/-threshold — simulates a hot
    mic input or aggressive AGC overshoot, a common real-room artifact TTS never
    produces. Purely deterministic (no RNG)."""
    boosted = pcm.astype(np.float64) * (10.0 ** (gain_db / 20.0))
    return np.clip(boosted, -threshold, threshold).astype(np.float32)


def apply_condition(name: str, pcm: np.ndarray, seed: int = 0) -> np.ndarray:
    """Dispatch by condition name — the single entry point run_asr_eval.py uses,
    so the eval script doesn't need to know each augmentation's parameters."""
    if name == "clean":
        return pcm.astype(np.float32).copy()
    if name == "snr20":
        return add_white_noise(pcm, 20.0, seed)
    if name == "snr10":
        return add_white_noise(pcm, 10.0, seed)
    if name == "snr5":
        return add_white_noise(pcm, 5.0, seed)
    if name == "pink10":
        return add_pink_noise(pcm, 10.0, seed)
    if name == "reverb":
        return add_reverb(pcm, seed=seed)
    if name == "fast":
        return change_speed(pcm, 1.1)
    if name == "slow":
        return change_speed(pcm, 0.9)
    if name == "clip":
        return gain_and_clip(pcm)
    raise ValueError(f"unknown condition: {name!r}")
