import pytest

from duet_agent.rate_limits import KeyedWindowLimiter, ProviderQuota, QuotaExceeded, SessionAdmission


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def test_provider_quota_enforces_rpm_and_recovers_after_window():
    clock = Clock()
    quota = ProviderQuota(requests_per_minute=2, requests_per_day=10, clock=clock)
    with quota.slot():
        pass
    with quota.slot():
        pass
    with pytest.raises(QuotaExceeded, match="requests_per_minute"):
        quota.acquire()
    clock.now += 60.01
    with quota.slot():
        pass


def test_provider_quota_releases_concurrency_after_exception():
    quota = ProviderQuota(requests_per_minute=5, requests_per_day=5, max_concurrent=1)
    with pytest.raises(RuntimeError):
        with quota.slot():
            raise RuntimeError("provider failed")
    assert quota.snapshot().concurrent_used == 0


def test_provider_quota_rejects_second_concurrent_request():
    quota = ProviderQuota(requests_per_minute=5, requests_per_day=5, max_concurrent=1)
    quota.acquire()
    try:
        with pytest.raises(QuotaExceeded, match="concurrent"):
            quota.acquire()
    finally:
        quota.release()


def test_daily_quota_survives_process_restart(tmp_path):
    clock = Clock()
    state = tmp_path / "gemini-quota.json"
    first = ProviderQuota(requests_per_minute=5, requests_per_day=1, clock=clock, state_path=state)
    with first.slot():
        pass
    restarted = ProviderQuota(requests_per_minute=5, requests_per_day=1, clock=clock, state_path=state)
    with pytest.raises(QuotaExceeded, match="requests_per_day"):
        restarted.acquire()


def test_keyed_limiter_isolated_by_client():
    clock = Clock()
    limiter = KeyedWindowLimiter(max_events=1, window_s=10, clock=clock)
    assert limiter.allow("a")[0]
    assert not limiter.allow("a")[0]
    assert limiter.allow("b")[0]
    clock.now += 10.01
    assert limiter.allow("a")[0]


def test_session_admission_reports_hourly_limit():
    clock = Clock()
    admission = SessionAdmission(per_hour=1, per_day=5, clock=clock)
    assert admission.allow("203.0.113.1")[0]
    allowed, retry, dimension = admission.allow("203.0.113.1")
    assert not allowed
    assert retry > 0
    assert dimension == "hourly"
