"""Process-local admission controls for the single-node Duet deployment.

These controls intentionally fail fast.  Waiting inside the live voice path turns
provider quota pressure into awkward silence; rejecting optional reasoning lets
the deterministic conversation controller keep the session responsive.

The VPS deployment runs one application process, so process-local state is the
correct first boundary.  A multi-replica deployment must replace this with a
shared atomic store (for example Redis) before increasing replica count.
"""

from __future__ import annotations

import os
import json
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class QuotaExceeded(RuntimeError):
    """A provider request was intentionally not sent."""

    def __init__(self, dimension: str, retry_after_s: float):
        self.dimension = dimension
        self.retry_after_s = max(float(retry_after_s), 0.0)
        super().__init__(f"{dimension} quota exhausted; retry in {self.retry_after_s:.1f}s")


@dataclass(frozen=True)
class QuotaSnapshot:
    rpm_limit: int
    rpm_used: int
    rpd_limit: int
    rpd_used: int
    concurrent_limit: int
    concurrent_used: int


class ProviderQuota:
    """Thread-safe rolling request and concurrency budget.

    A rolling 24-hour window is deliberately stricter than Gemini's documented
    midnight-Pacific daily reset and avoids clock/timezone reset edge cases.
    """

    MINUTE = 60.0
    DAY = 86_400.0

    def __init__(
        self,
        *,
        requests_per_minute: int,
        requests_per_day: int,
        max_concurrent: int = 1,
        clock=time.time,
        state_path: Path | None = None,
    ) -> None:
        if min(requests_per_minute, requests_per_day, max_concurrent) < 1:
            raise ValueError("quota limits must be positive")
        self.requests_per_minute = requests_per_minute
        self.requests_per_day = requests_per_day
        self.max_concurrent = max_concurrent
        self._clock = clock
        self._state_path = state_path
        self._minute: deque[float] = deque()
        self._day: deque[float] = deque()
        self._in_flight = 0
        self._lock = threading.Lock()
        self._load_state()

    @classmethod
    def from_env(cls) -> "ProviderQuota":
        configured_path = os.environ.get("GEMINI_QUOTA_STATE_PATH", "").strip()
        return cls(
            requests_per_minute=int(os.environ.get("GEMINI_RPM_LIMIT", "8")),
            requests_per_day=int(os.environ.get("GEMINI_RPD_LIMIT", "100")),
            max_concurrent=int(os.environ.get("GEMINI_CONCURRENT_LIMIT", "1")),
            state_path=Path(configured_path) if configured_path else None,
        )

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            values = payload.get("day_events", [])
            if not isinstance(values, list) or not all(isinstance(value, (int, float)) for value in values):
                raise ValueError("day_events must be a numeric list")
            now = self._clock()
            self._day.extend(sorted(float(value) for value in values if now - self.DAY < value <= now + 1))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            # Corrupt quota state must never silently reset a public API budget.
            raise RuntimeError(f"cannot load Gemini quota state {self._state_path}: {error}") from error

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"day_events": list(self._day)}), encoding="utf-8")
        temporary.replace(self._state_path)

    @staticmethod
    def _prune(events: deque[float], threshold: float) -> None:
        while events and events[0] <= threshold:
            events.popleft()

    def acquire(self) -> None:
        now = self._clock()
        with self._lock:
            self._prune(self._minute, now - self.MINUTE)
            self._prune(self._day, now - self.DAY)
            if self._in_flight >= self.max_concurrent:
                raise QuotaExceeded("concurrent", 0.5)
            if len(self._minute) >= self.requests_per_minute:
                raise QuotaExceeded("requests_per_minute", self.MINUTE - (now - self._minute[0]))
            if len(self._day) >= self.requests_per_day:
                raise QuotaExceeded("requests_per_day", self.DAY - (now - self._day[0]))
            self._minute.append(now)
            self._day.append(now)
            try:
                self._persist_state()
            except OSError:
                self._minute.pop()
                self._day.pop()
                raise
            self._in_flight += 1

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    @contextmanager
    def slot(self):
        self.acquire()
        try:
            yield
        finally:
            self.release()

    def snapshot(self) -> QuotaSnapshot:
        now = self._clock()
        with self._lock:
            self._prune(self._minute, now - self.MINUTE)
            self._prune(self._day, now - self.DAY)
            return QuotaSnapshot(
                rpm_limit=self.requests_per_minute,
                rpm_used=len(self._minute),
                rpd_limit=self.requests_per_day,
                rpd_used=len(self._day),
                concurrent_limit=self.max_concurrent,
                concurrent_used=self._in_flight,
            )


class KeyedWindowLimiter:
    """Bounded per-client sliding-window admission control."""

    def __init__(self, *, max_events: int, window_s: float, max_keys: int = 10_000, clock=time.monotonic):
        if max_events < 1 or window_s <= 0 or max_keys < 1:
            raise ValueError("limiter bounds must be positive")
        self.max_events = max_events
        self.window_s = float(window_s)
        self.max_keys = max_keys
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        now = self._clock()
        with self._lock:
            events = self._events[key]
            ProviderQuota._prune(events, now - self.window_s)
            if len(events) >= self.max_events:
                return False, max(0.0, self.window_s - (now - events[0]))
            events.append(now)
            if len(self._events) > self.max_keys:
                stale = [candidate for candidate, values in self._events.items() if not values or values[-1] <= now - self.window_s]
                for candidate in stale[: len(self._events) - self.max_keys]:
                    self._events.pop(candidate, None)
            return True, 0.0


class SessionAdmission:
    """Per-IP protection around the expensive public WebSocket session."""

    def __init__(self, *, per_hour: int, per_day: int, clock=time.monotonic):
        self.hour = KeyedWindowLimiter(max_events=per_hour, window_s=3_600, clock=clock)
        self.day = KeyedWindowLimiter(max_events=per_day, window_s=86_400, clock=clock)

    @classmethod
    def from_env(cls) -> "SessionAdmission":
        return cls(
            per_hour=int(os.environ.get("SESSION_LIMIT_PER_IP_HOUR", "3")),
            per_day=int(os.environ.get("SESSION_LIMIT_PER_IP_DAY", "10")),
        )

    def allow(self, client_id: str) -> tuple[bool, float, str]:
        allowed, retry = self.day.allow(client_id)
        if not allowed:
            return False, retry, "daily"
        allowed, retry = self.hour.allow(client_id)
        if not allowed:
            return False, retry, "hourly"
        return True, 0.0, ""


_GEMINI_QUOTA: ProviderQuota | None = None
_GEMINI_QUOTA_LOCK = threading.Lock()


def gemini_quota() -> ProviderQuota:
    global _GEMINI_QUOTA
    with _GEMINI_QUOTA_LOCK:
        if _GEMINI_QUOTA is None:
            _GEMINI_QUOTA = ProviderQuota.from_env()
        return _GEMINI_QUOTA
