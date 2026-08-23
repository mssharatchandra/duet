FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DUET_TELEMETRY_LOG=/data/telemetry/events.jsonl

RUN groupadd --system duet && useradd --system --gid duet --home-dir /app duet
WORKDIR /app

COPY web-demo/requirements-container.txt /tmp/requirements.txt
RUN pip install --requirement /tmp/requirements.txt

COPY agent/duet_agent /app/agent/duet_agent
COPY web-demo /app/web-demo
RUN mkdir -p /data/telemetry /app/.local /app/eval/asr/sessions \
    && chown -R duet:duet /app /data

USER duet
EXPOSE 8990

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8990/healthz', timeout=2).read()"

CMD ["python", "web-demo/server.py", "--voice-stack", "open", "--asr", "sarvam", "--tts-backend", "sarvam-ws", "--barge-in", "--port", "8990"]
