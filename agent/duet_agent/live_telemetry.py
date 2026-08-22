"""Live-session telemetry for the browser and future telephony adapters.

The audio path must never wait for observability. Metrics are in-memory and
lock-bounded; JSON logs and Langfuse ingestion are queued to daemon workers;
Postgres persistence happens after disconnect on a daemon thread. Transcript
content is redacted by default and can be enabled only with explicit consent.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import statistics
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from .env import repo_root
from .telemetry import CallStore, LangfuseTracer, cost_fields

HISTOGRAM_BUCKETS_MS = (25, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10_000)
CONTENT_KEYS = {"text", "raw_text", "transcript", "user_utterance", "evidence", "question", "answer"}
LOGGED_EVENT_TYPES = {"session", "asr_state", "brain", "brain_state", "tts_state", "policy", "action", "error", "playback_cancel"}
SPAN_EVENT_TYPES = {"asr_state", "brain", "tts_state", "policy", "action", "error", "playback_cancel"}


def _escape_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')[:80]


def _labels_text(labels: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
    values = list(labels)
    if extra is not None:
        values.append(extra)
    if not values:
        return ""
    return "{" + ",".join(f'{key}="{_escape_label(value)}"' for key, value in values) + "}"


class MetricsRegistry:
    """Small Prometheus text registry with bounded-cardinality labels."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)
        self._help: dict[str, str] = {}

    @staticmethod
    def _key(name: str, labels: dict[str, object] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        safe_name = re.sub(r"[^a-zA-Z0-9_:]", "_", name)
        safe_labels = tuple(sorted((re.sub(r"[^a-zA-Z0-9_]", "_", key), str(value)[:80]) for key, value in (labels or {}).items()))
        return safe_name, safe_labels

    def inc(self, name: str, amount: float = 1.0, *, labels: dict[str, object] | None = None, help_text: str = "") -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += amount
            self._help.setdefault(key[0], help_text or key[0])

    def gauge_add(self, name: str, amount: float, *, labels: dict[str, object] | None = None, help_text: str = "") -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] += amount
            self._help.setdefault(key[0], help_text or key[0])

    def observe(self, name: str, value: float, *, labels: dict[str, object] | None = None, help_text: str = "") -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(float(value))
            self._help.setdefault(key[0], help_text or key[0])

    def render(self) -> str:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = {key: list(values) for key, values in self._histograms.items()}
            help_map = dict(self._help)
        lines: list[str] = []
        for metric_type, values in (("counter", counters), ("gauge", gauges)):
            names = sorted({name for name, _ in values})
            for name in names:
                lines.extend((f"# HELP {name} {help_map.get(name, name)}", f"# TYPE {name} {metric_type}"))
                for (metric_name, labels), value in sorted(values.items()):
                    if metric_name == name:
                        lines.append(f"{name}{_labels_text(labels)} {value:g}")
        names = sorted({name for name, _ in histograms})
        for name in names:
            lines.extend((f"# HELP {name} {help_map.get(name, name)}", f"# TYPE {name} histogram"))
            for (metric_name, labels), values in sorted(histograms.items()):
                if metric_name != name:
                    continue
                for bucket in HISTOGRAM_BUCKETS_MS:
                    count = sum(value <= bucket for value in values)
                    lines.append(f'{name}_bucket{_labels_text(labels, ("le", str(bucket)))} {count}')
                lines.append(f'{name}_bucket{_labels_text(labels, ("le", "+Inf"))} {len(values)}')
                lines.append(f"{name}_count{_labels_text(labels)} {len(values)}")
                lines.append(f"{name}_sum{_labels_text(labels)} {sum(values):g}")
        return "\n".join(lines) + "\n"


METRICS = MetricsRegistry()


def _redact(value: object) -> dict[str, object]:
    raw = json.dumps(value, sort_keys=True, default=str) if not isinstance(value, str) else value
    return {
        "redacted": True,
        "characters": len(raw),
        "sha256": hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest(),
    }


def safe_payload(payload: dict, capture_content: bool) -> dict:
    if capture_content:
        return payload
    return {key: (_redact(value) if key in CONTENT_KEYS else value) for key, value in payload.items()}


class JsonEventSink:
    """Bounded asynchronous JSONL writer. A full queue drops logs, never audio."""

    def __init__(self, path: Path | None = None, max_queue: int = 4096) -> None:
        configured = os.environ.get("DUET_TELEMETRY_LOG", ".local/telemetry/events.jsonl")
        self.path = path or (repo_root() / configured)
        self.queue: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self.dropped = 0
        threading.Thread(target=self._worker, name="duet-json-telemetry", daemon=True).start()

    def write(self, event: dict) -> None:
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1
            METRICS.inc("duet_telemetry_dropped_events_total", help_text="Structured telemetry events dropped locally")

    def _worker(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", buffering=1) as output:
                while True:
                    event = self.queue.get()
                    output.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        except Exception:  # noqa: BLE001 -- observability is fail-silent by design
            return


_SINKS: dict[Path, JsonEventSink] = {}
_SINKS_LOCK = threading.Lock()


def default_sink() -> JsonEventSink:
    path = repo_root() / os.environ.get("DUET_TELEMETRY_LOG", ".local/telemetry/events.jsonl")
    with _SINKS_LOCK:
        if path not in _SINKS:
            _SINKS[path] = JsonEventSink(path)
        return _SINKS[path]


class LiveSessionTelemetry:
    """One correlated trace, metric set and durable call summary per session."""

    def __init__(self, session_id: str, mode: str, providers: dict[str, object], *,
                 metrics: MetricsRegistry | None = None, tracer=None, store=None, sink=None) -> None:
        self.session_id = session_id
        self.mode = mode
        self.providers = providers
        self.metrics = metrics or METRICS
        self.tracer = tracer or LangfuseTracer()
        self.store = store or CallStore()
        self.sink = sink or default_sink()
        self.capture_content = os.environ.get("DUET_TRACE_CONTENT", "false").lower() in {"1", "true", "yes"}
        self.started_wall = time.time()
        self.started_perf = time.perf_counter()
        self.trace_id = self.tracer.trace("duet-live-session", {"session_id": session_id, "mode": mode, **providers})
        self.finished = False
        self.user_turns = 0
        self.agent_turns = 0
        self.interruptions = 0
        self.backchannels = 0
        self.response_latencies_ms: list[float] = []
        self.pending_endpoints: deque[float] = deque()
        self.metrics.inc("duet_sessions_total", labels={"mode": mode}, help_text="Voice sessions started")
        self.metrics.gauge_add("duet_sessions_active", 1, labels={"mode": mode}, help_text="Currently active voice sessions")
        self.event({"type": "session", "state": "started", "providers": providers})

    def attach_brain(self, brain) -> None:
        if brain is None:
            return
        brain.tracer = self.tracer
        brain.trace_id = self.trace_id

    def mark_user_turn(self, endpoint_latency_ms: float) -> None:
        self.user_turns += 1
        self.pending_endpoints.append(time.perf_counter() - max(endpoint_latency_ms, 0.0) / 1000)
        self.metrics.inc("duet_user_turns_total", labels={"mode": self.mode}, help_text="Accepted user turns")
        self.metrics.observe("duet_asr_endpoint_latency_ms", endpoint_latency_ms, labels={"mode": self.mode}, help_text="Speech end to accepted final transcript")

    def mark_first_audio(self) -> None:
        self.agent_turns += 1
        self.metrics.inc("duet_agent_turns_total", labels={"mode": self.mode}, help_text="Agent utterances that produced audio")
        if self.pending_endpoints:
            latency_ms = (time.perf_counter() - self.pending_endpoints.popleft()) * 1000
            self.response_latencies_ms.append(latency_ms)
            self.metrics.observe("duet_response_latency_ms", latency_ms, labels={"mode": self.mode}, help_text="Caller speech end to first agent audio")

    def event(self, payload: dict) -> None:
        event_type = str(payload.get("type") or "unknown")[:40]
        state = str(payload.get("state") or "none")[:60]
        self.metrics.inc("duet_events_total", labels={"type": event_type, "state": state}, help_text="Session events by type and state")
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)):
            metric = {
                "brain": "duet_reasoning_latency_ms",
                "action": "duet_action_latency_ms",
            }.get(event_type)
            if event_type == "tts_state" and state == "first_audio":
                metric = "duet_tts_first_audio_latency_ms"
            if metric:
                self.metrics.observe(metric, float(latency), labels={"mode": self.mode}, help_text=f"{event_type} latency")
        if event_type == "playback_cancel":
            self.interruptions += 1
            self.metrics.inc("duet_interruptions_total", labels={"mode": self.mode}, help_text="Agent playback interruptions")
        if event_type == "policy" and state == "listener_backchannel":
            self.backchannels += 1
        if event_type == "error":
            self.metrics.inc("duet_errors_total", labels={"component": str(payload.get("component") or "session")[:40]}, help_text="Voice pipeline errors")
        if event_type == "tts_state" and state == "first_audio":
            self.mark_first_audio()

        now = time.time()
        safe = safe_payload(dict(payload), self.capture_content)
        record = {
            "timestamp": now,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "mode": self.mode,
            "elapsed_ms": round((time.perf_counter() - self.started_perf) * 1000, 2),
            **safe,
        }
        # Partial hypotheses and calibration ticks are high-volume; metrics retain
        # their counts while logs keep only durable decision points by default.
        high_volume = event_type == "asr_state" and state in {"partial", "listening", "calibrating"}
        if event_type in LOGGED_EVENT_TYPES and (not high_volume or os.environ.get("DUET_LOG_PARTIALS") == "true"):
            self.sink.write(record)
        if event_type in SPAN_EVENT_TYPES and not high_volume:
            self.tracer.span(
                self.trace_id,
                f"voice.{event_type}.{state}",
                now,
                now,
                metadata=safe,
                error=event_type == "error",
            )

    def finish(self, reason: str, brain=None) -> None:
        if self.finished:
            return
        self.finished = True
        duration_s = max(time.perf_counter() - self.started_perf, 0.001)
        self.metrics.gauge_add("duet_sessions_active", -1, labels={"mode": self.mode}, help_text="Currently active voice sessions")
        self.metrics.inc("duet_session_ends_total", labels={"mode": self.mode, "reason": reason[:40]}, help_text="Voice sessions ended")
        stats = getattr(brain, "stats", None)
        tokens_in = int(getattr(stats, "tokens_in", 0))
        tokens_out = int(getattr(stats, "tokens_out", 0))
        model = getattr(brain, "model", "")
        reasoning_usd = float(stats.cost_usd(model)) if stats is not None else 0.0
        p50 = statistics.median(self.response_latencies_ms) if self.response_latencies_ms else None
        p95 = None
        if self.response_latencies_ms:
            ordered = sorted(self.response_latencies_ms)
            # Nearest-rank percentile: even short calls must report their slow
            # tail, and p95 must never be lower than the median.
            p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
        costs = cost_fields(0.0, reasoning_usd, duration_s)
        langfuse_drops = int(getattr(self.tracer, "dropped_batches", 0))
        if langfuse_drops:
            self.metrics.inc(
                "duet_langfuse_dropped_batches_total",
                langfuse_drops,
                help_text="Langfuse ingestion batches dropped before export",
            )
        record = {
            "call_id": self.session_id,
            "mode": f"live-{self.mode}",
            "scenario": "browser-live",
            "duration_s": duration_s,
            "user_utterances": self.user_turns,
            "takeovers": self.interruptions,
            "backchannels": self.backchannels,
            "response_latency_ms_p50": p50,
            "response_latency_ms_p95": p95,
            "gpu_seconds": 0.0,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "langfuse_trace_id": self.trace_id,
            **costs,
        }
        self.event({"type": "session", "state": "ended", "reason": reason, "summary": record})
        threading.Thread(target=self.store.insert, args=(record,), name="duet-call-store", daemon=True).start()
