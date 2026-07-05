# Duet Phase 3 — telemetry: Langfuse tracing + Postgres call records.
#
# Two hard rules:
#   1. Fail-silent. Telemetry must NEVER break or slow a call — every network/db
#      touch happens on a daemon thread or inside a broad try/except. If the
#      stack isn't running, the call still works and metrics land in JSONL only.
#   2. Stdlib transport. Langfuse's ingestion API is a simple authed POST; a
#      pinned SDK isn't worth a dependency for two event types.

import base64
import json
import os
import threading
import time
import urllib.request
import uuid

# $/hr for the GPU class we'd deploy on (RunPod L4-class, DECISIONS.md 0007).
# Local Apple-Silicon runs cost $0 — this prices what production WOULD cost.
GPU_USD_PER_HOUR = float(os.environ.get("GPU_USD_PER_HOUR", "0.40"))

CALLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id serial PRIMARY KEY,
  ts timestamptz DEFAULT now(),
  call_id text UNIQUE,
  mode text,
  scenario text,
  duration_s real,
  user_utterances int,
  takeovers int,
  backchannels int,
  takeover_rate real,
  overlap_ratio real,
  response_latency_ms_p50 real,
  response_latency_ms_p95 real,
  gpu_seconds real,
  tokens_in int,
  tokens_out int,
  reasoning_cost_usd real,
  gpu_cost_usd real,
  cost_per_min_usd real,
  langfuse_trace_id text
);
"""


def _iso(ts: float | None = None) -> str:
    ts = time.time() if ts is None else ts
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{int(ts % 1 * 1000):03d}Z"


def cost_fields(gpu_seconds: float, reasoning_usd: float, duration_s: float) -> dict:
    gpu_usd = gpu_seconds * GPU_USD_PER_HOUR / 3600
    minutes = max(duration_s / 60, 1e-9)
    return {
        "gpu_cost_usd": round(gpu_usd, 6),
        "reasoning_cost_usd": round(reasoning_usd, 6),
        "cost_per_min_usd": round((gpu_usd + reasoning_usd) / minutes, 6),
    }


class LangfuseTracer:
    def __init__(self, host: str | None = None, public_key: str | None = None, secret_key: str | None = None):
        self.host = (host or os.environ.get("LANGFUSE_HOST", "")).rstrip("/")
        pk = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        sk = secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")
        self.enabled = bool(self.host and pk and sk)
        self._auth = "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode() if self.enabled else ""

    def trace(self, name: str, metadata: dict | None = None) -> str:
        trace_id = str(uuid.uuid4())
        self._send_async(
            [{"id": str(uuid.uuid4()), "type": "trace-create", "timestamp": _iso(),
              "body": {"id": trace_id, "name": name, "metadata": metadata or {}}}]
        )
        return trace_id

    def generation(self, trace_id: str, name: str, model: str, input_text: str, output_text: str,
                   tokens_in: int, tokens_out: int, start_ts: float, end_ts: float, error: bool = False) -> None:
        self._send_async(
            [{"id": str(uuid.uuid4()), "type": "generation-create", "timestamp": _iso(),
              "body": {
                  "id": str(uuid.uuid4()), "traceId": trace_id, "name": name, "model": model,
                  "input": input_text, "output": output_text,
                  "usage": {"input": tokens_in, "output": tokens_out},
                  "startTime": _iso(start_ts), "endTime": _iso(end_ts),
                  "level": "ERROR" if error else "DEFAULT",
              }}]
        )

    def _send_async(self, batch: list) -> None:
        if not self.enabled:
            return
        threading.Thread(target=self._send, args=(batch,), daemon=True).start()

    def _send(self, batch: list) -> None:
        try:
            req = urllib.request.Request(
                f"{self.host}/api/public/ingestion",
                data=json.dumps({"batch": batch}).encode(),
                headers={"Content-Type": "application/json", "Authorization": self._auth},
            )
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass  # rule 1


class CallStore:
    """Writes one row per call into Postgres (the Grafana dashboard's source)."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        self._warned = False

    def insert(self, record: dict) -> bool:
        if not self.dsn:
            return False
        try:
            import psycopg  # optional dep: uv pip install -e '.[bench]'

            cols = [c.strip().split()[0] for c in CALLS_SCHEMA.split("(", 1)[1].rsplit(")", 1)[0].split(",")]
            cols = [c for c in cols if c in record]
            with psycopg.connect(self.dsn, connect_timeout=3) as conn:
                conn.execute(CALLS_SCHEMA)
                conn.execute(
                    f"INSERT INTO calls ({', '.join(cols)}) VALUES ({', '.join('%s' for _ in cols)})"
                    " ON CONFLICT (call_id) DO NOTHING",
                    [record[c] for c in cols],
                )
            return True
        except Exception as e:
            if not self._warned:
                self._warned = True
                print(f"[telemetry] postgres unavailable ({type(e).__name__}) — call records go to JSONL only")
            return False
