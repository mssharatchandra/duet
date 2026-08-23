# Codebase map and Graphify output

Graphify is an analysis tool, not a runtime dependency or a second repository. Version 0.9.48 was run in
local code-only mode. Its generated graph currently lives at:

```text
/Users/sharat/Downloads/CURIOUS/duet/graphify-out/
├── graph.json       # 714 nodes, 1,552 edges after Hermes removal
├── manifest.json
└── cache/
```

`graphify-out/` is intentionally gitignored because it is a machine-specific derived index. Regenerate it
from the Duet root after structural changes:

```bash
graphify extract . --code-only --output graphify-out
```

The durable, human-reviewed map is [ARCHITECTURE.md](ARCHITECTURE.md). The most important Graphify finding
was that `web-demo/server.py::Session` is the highest-coupling hub. That is why the production migration is
a strangler extraction—transport, turn control, conversation planning and speech egress become typed
components one at a time—rather than a big-bang rewrite.

## Read the repository in dependency order

1. `web-demo/static/index.html` and its AudioWorklet: browser audio and safe UI trace.
2. `web-demo/server.py`: session ownership and concurrency boundary.
3. `agent/duet_agent/turns.py`: partial/final transcript commit semantics.
4. `agent/duet_agent/persona.py`: grounded facts, policies and deterministic intent rules.
5. `agent/duet_agent/reasoning.py`: asynchronous Gemini structured planner.
6. `agent/duet_agent/rate_limits.py`: provider and public-session admission.
7. `agent/duet_agent/tts.py` and `asr.py`: provider/local speech abstractions.
8. `agent/duet_agent/actions.py`: idempotent side-effect boundary.
9. `agent/duet_agent/live_telemetry.py` and `telemetry.py`: metrics, traces, logs and call summaries.
10. `agent/tests/` and `eval/`: executable behavioral specification.

Use `rg "def _accept_transcript|def interrupt_playback|def _poll_brain" web-demo/server.py` to locate the
three control points that explain most live behavior.
