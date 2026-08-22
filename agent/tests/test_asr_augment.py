import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval" / "asr"))

import augment  # noqa: E402 — eval module path is added explicitly above


def _tone(n: int = 24_000, freq: float = 220.0, sr: int = 24_000) -> np.ndarray:
    t = np.arange(n) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# ---------------------------------------------------------------------------
# determinism: same inputs (incl. seed) -> bit-identical output


def test_white_noise_is_deterministic():
    pcm = _tone()
    a = augment.add_white_noise(pcm, 10.0, seed=42)
    b = augment.add_white_noise(pcm, 10.0, seed=42)
    np.testing.assert_array_equal(a, b)


def test_white_noise_different_seed_differs():
    pcm = _tone()
    a = augment.add_white_noise(pcm, 10.0, seed=1)
    b = augment.add_white_noise(pcm, 10.0, seed=2)
    assert not np.array_equal(a, b)


def test_pink_noise_is_deterministic():
    pcm = _tone()
    a = augment.add_pink_noise(pcm, 10.0, seed=7)
    b = augment.add_pink_noise(pcm, 10.0, seed=7)
    np.testing.assert_array_equal(a, b)


def test_reverb_is_deterministic():
    pcm = _tone()
    a = augment.add_reverb(pcm, seed=3)
    b = augment.add_reverb(pcm, seed=3)
    np.testing.assert_array_equal(a, b)


def test_apply_condition_is_deterministic_across_all_conditions():
    pcm = _tone()
    for name in augment.CONDITIONS:
        a = augment.apply_condition(name, pcm, seed=5)
        b = augment.apply_condition(name, pcm, seed=5)
        np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# SNR mixing actually hits the target ratio


def test_white_noise_hits_target_snr():
    rng = np.random.default_rng(0)
    pcm = (rng.standard_normal(48_000) * 0.3).astype(np.float32)  # noise-like "signal"
    for snr_db in (20.0, 10.0, 5.0):
        noisy = augment.add_white_noise(pcm, snr_db, seed=123)
        added_noise = noisy - pcm
        sig_power = np.mean(pcm.astype(np.float64) ** 2)
        noise_power = np.mean(added_noise.astype(np.float64) ** 2)
        measured_snr = 10 * np.log10(sig_power / noise_power)
        assert abs(measured_snr - snr_db) < 0.5


def test_lower_snr_db_means_louder_noise():
    pcm = _tone()
    quiet_noise = augment.add_white_noise(pcm, 20.0, seed=9) - pcm
    loud_noise = augment.add_white_noise(pcm, 5.0, seed=9) - pcm
    assert np.mean(loud_noise**2) > np.mean(quiet_noise**2)


def test_silence_is_untouched_by_noise_mixing():
    silence = np.zeros(1000, dtype=np.float32)
    out = augment.add_white_noise(silence, 10.0, seed=1)
    np.testing.assert_array_equal(out, silence)


# ---------------------------------------------------------------------------
# reverb


def test_reverb_output_same_length_as_input():
    pcm = _tone(10_000)
    out = augment.add_reverb(pcm, seed=1)
    assert len(out) == len(pcm)


def test_reverb_does_not_clip():
    pcm = _tone(10_000) * 0.99
    out = augment.add_reverb(pcm, seed=1, wet=0.8)
    assert np.max(np.abs(out)) <= 1.0 + 1e-6


def test_reverb_changes_signal():
    pcm = _tone(10_000)
    out = augment.add_reverb(pcm, seed=1)
    assert not np.allclose(out, pcm)


def test_reverb_wet_zero_is_dry_signal():
    pcm = _tone(5000)
    out = augment.add_reverb(pcm, seed=1, wet=0.0)
    np.testing.assert_allclose(out, pcm, atol=1e-5)


# ---------------------------------------------------------------------------
# speed perturbation


def test_speed_up_shortens_clip():
    pcm = _tone(24_000)
    out = augment.change_speed(pcm, 1.1)
    assert len(out) < len(pcm)


def test_slow_down_lengthens_clip():
    pcm = _tone(24_000)
    out = augment.change_speed(pcm, 0.9)
    assert len(out) > len(pcm)


def test_speed_factor_one_preserves_length():
    pcm = _tone(24_000)
    out = augment.change_speed(pcm, 1.0)
    assert len(out) == len(pcm)


def test_speed_rejects_nonpositive_factor():
    pcm = _tone(1000)
    try:
        augment.change_speed(pcm, 0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_speed_handles_tiny_input():
    out = augment.change_speed(np.array([0.1], dtype=np.float32), 1.1)
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# gain / clip


def test_gain_and_clip_saturates_at_threshold():
    pcm = _tone(1000)  # amplitude 0.5
    out = augment.gain_and_clip(pcm, gain_db=20.0, threshold=1.0)  # 10x boost -> amplitude 5.0
    assert np.max(np.abs(out)) <= 1.0
    assert np.isclose(np.max(out), 1.0, atol=1e-3)


def test_gain_and_clip_no_boost_below_threshold_is_unclipped():
    pcm = _tone(1000) * 0.1  # amplitude 0.05
    out = augment.gain_and_clip(pcm, gain_db=0.0, threshold=1.0)
    np.testing.assert_allclose(out, pcm, atol=1e-6)


def test_gain_and_clip_is_deterministic():
    pcm = _tone(1000)
    a = augment.gain_and_clip(pcm, gain_db=12.0)
    b = augment.gain_and_clip(pcm, gain_db=12.0)
    np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# dispatch


def test_apply_condition_clean_is_identity():
    pcm = _tone()
    out = augment.apply_condition("clean", pcm, seed=1)
    np.testing.assert_array_equal(out, pcm)
    assert out is not pcm  # defensive copy, not aliasing


def test_apply_condition_unknown_raises():
    try:
        augment.apply_condition("nonsense", _tone(), seed=0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_apply_condition_covers_all_advertised_conditions():
    pcm = _tone()
    for name in augment.CONDITIONS:
        out = augment.apply_condition(name, pcm, seed=0)
        assert isinstance(out, np.ndarray)
        assert out.dtype == np.float32
        assert len(out) > 0


def test_all_condition_outputs_are_float32():
    pcm = _tone()
    for name in augment.CONDITIONS:
        out = augment.apply_condition(name, pcm, seed=0)
        assert out.dtype == np.float32
