import json
import time
from types import SimpleNamespace

from duet_agent.live_telemetry import LiveSessionTelemetry, MetricsRegistry, safe_payload
from duet_agent.telemetry import LangfuseTracer


class FakeTracer:
    def __init__(self):
        self.spans = []

    def trace(self, name, metadata):
        self.trace = (name, metadata)
        return "trace-1"

    def span(self, trace_id, name, start_ts, end_ts, metadata=None, error=False):
        self.spans.append((trace_id, name, metadata, error))


class FakeSink:
    def __init__(self):
        self.events = []

    def write(self, event):
        self.events.append(event)


class FakeStore:
    def __init__(self):
        self.records = []

    def insert(self, record):
        self.records.append(record)
        return True


def test_metrics_registry_renders_counter_gauge_and_cumulative_histogram():
    metrics = MetricsRegistry()
    metrics.inc("duet_test_total", labels={"state": "ok"})
    metrics.gauge_add("duet_active", 1, labels={"mode": "sdr"})
    metrics.observe("duet_latency_ms", 40, labels={"mode": "sdr"})
    metrics.observe("duet_latency_ms", 600, labels={"mode": "sdr"})

    rendered = metrics.render()

    assert 'duet_test_total{state="ok"} 1' in rendered
    assert 'duet_active{mode="sdr"} 1' in rendered
    assert 'duet_latency_ms_bucket{mode="sdr",le="50"} 1' in rendered
    assert 'duet_latency_ms_bucket{mode="sdr",le="750"} 2' in rendered
    assert 'duet_latency_ms_count{mode="sdr"} 2' in rendered


def test_safe_payload_redacts_conversation_content_but_keeps_operational_fields():
    safe = safe_payload({"text": "my budget is two crore", "state": "result", "latency_ms": 123}, False)

    assert safe["text"]["redacted"] is True
    assert safe["text"]["characters"] == len("my budget is two crore")
    assert safe["state"] == "result"
    assert safe["latency_ms"] == 123
    json.dumps(safe)


def test_langfuse_redacts_content_and_shares_one_backend_exporter(monkeypatch):
    monkeypatch.setenv("DUET_TRACE_CONTENT", "false")
    first = LangfuseTracer(host="http://langfuse.invalid", public_key="pk-test", secret_key="sk-test")
    second = LangfuseTracer(host="http://langfuse.invalid", public_key="pk-test", secret_key="sk-test")

    assert first._exporter is second._exporter
    assert first._content("private transcript") == {
        "redacted": True,
        "characters": len("private transcript"),
        "sha256": "3b03a4e528fd010c997c47ee71295a7066d035e2d125cdf1ee642655d9074df3",
    }


def test_live_session_correlates_events_metrics_trace_and_call_record(monkeypatch):
    monkeypatch.setenv("DUET_TRACE_CONTENT", "false")
    metrics = MetricsRegistry()
    tracer = FakeTracer()
    sink = FakeSink()
    store = FakeStore()
    telemetry = LiveSessionTelemetry(
        "session-1",
        "sdr",
        {"asr": "sarvam", "tts": "sarvam-ws"},
        metrics=metrics,
        tracer=tracer,
        sink=sink,
        store=store,
    )
    brain = SimpleNamespace(
        model="gemini-test",
        stats=SimpleNamespace(tokens_in=20, tokens_out=10, cost_usd=lambda _model: 0.001),
        tracer=None,
        trace_id=None,
    )
    telemetry.attach_brain(brain)
    telemetry.mark_user_turn(120)
    telemetry.event({"type": "brain", "state": "ready", "latency_ms": 400, "text": "private reply"})
    telemetry.event({"type": "tts_state", "state": "first_audio", "latency_ms": 180})
    telemetry.mark_user_turn(0)
    time.sleep(0.002)
    telemetry.event({"type": "tts_state", "state": "first_audio", "latency_ms": 175})
    telemetry.event({"type": "playback_cancel", "state": "user_barge_in", "transcript": "wait"})
    telemetry.finish("client_disconnect", brain)

    for _ in range(50):
        if store.records:
            break
        time.sleep(0.01)

    assert brain.trace_id == "trace-1"
    assert tracer.spans
    assert any(event["trace_id"] == "trace-1" for event in sink.events)
    assert all(event.get("text", {}).get("redacted", False) for event in sink.events if "text" in event)
    assert store.records[0]["tokens_in"] == 20
    assert store.records[0]["takeovers"] == 1
    assert store.records[0]["response_latency_ms_p50"] is not None
    assert store.records[0]["response_latency_ms_p95"] >= store.records[0]["response_latency_ms_p50"]
    rendered = metrics.render()
    assert 'duet_sessions_active{mode="sdr"} 0' in rendered
    assert "duet_response_latency_ms_count" in rendered
