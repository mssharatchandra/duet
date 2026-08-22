# Duet evaluation

Duet treats evals as the executable product specification. A change is not an improvement merely because it sounds plausible; it must move the intended metric without regressing grounding, safety or task completion.

## Current suites

| Suite | Command | Measures | Status |
|---|---|---|---|
| Unit and interaction flow | `agent/.venv/bin/pytest -q agent/tests` | Turn assembly, interruption policy, actions, ASR/TTS adapters, reasoning contracts | CI gate |
| Live reasoning golden set | `python eval/reasoning/run_eval.py` | 17 ASBL scenarios: intent, content, grounding, objections and forbidden behavior | Push CI gate at ≥90%; uses Gemini API |
| End-to-end synthetic caller | `web-demo/.venv/bin/python scripts/smoke-live-demo.py` | Browser protocol, realtime ASR, reasoning, TTS, playback and barge-in cancellation | Manual real-service smoke |
| ASR discrimination | `agent/.venv/bin/python eval/asr/run_asr_eval.py --augment ...` | WER and real-time factor under noise, reverb and speed changes | Implemented; synthetic speech limitations |
| TTS benchmark | `agent/.venv/bin/python eval/tts/bench_tts.py` | Time to first audio, real-time factor and load time | Implemented; does not measure naturalness |
| Duplex benchmark | `agent/.venv/bin/python eval/bench/run_bench.py` | Takeover Rate, overlap, handoff latency and estimated cost | Implemented, but existing result files predate current Aira runtime |
| Blind human study | Protocol in `docs/BLIND_EVAL.md` | Naturalness, listening, control and preference | Not yet completed |

## Current evidence boundary

- The automated suite currently contains **149 passing tests**.
- The latest real-service synthetic smoke measured **2.126 s** from final speech end to first audible audio and **192 ms** to yield playback after a synthetic barge-in.
- The local ASR discrimination set currently favors Parakeet TDT 0.6B over the tested faster-whisper and MLX Whisper candidates, but it is based on synthesized and augmented audio rather than a representative caller corpus.
- The first human Aira trial was treated as a failed naturalness result. It revealed rushed prosody, weak acknowledgments, repetition and bad interruption recovery; the fixes have not yet passed a blind second trial.
- `eval/bench/RESULTS.md` and `eval/bench/out/` are historical development artifacts from an earlier persona/architecture. They must not be used as current Aira benchmark claims.

## Research matrix

The proposed paper needs an ablation switchboard, not only model comparisons:

1. sequential cascade;
2. concurrent streaming without partial speculation;
3. stable-partial speculation without semantic confirmation;
4. speculation with final semantic confirmation;
5. confirmation plus interruption repair;
6. complete system with grounding and capability gates.

Each variant should run the same scripted semantics and the same audio. Report p50 and p95 latency, wrong starts, speculative cancellation rate, interruption yield, inappropriate overlap, task success, factual/policy failures, human naturalness and cost per minute.

See [the research direction](../docs/RESEARCH_DIRECTION.md) for hypotheses and publication gates.

## Observability path

`eval/bench/run_bench.py` creates one Langfuse trace per benchmark call and writes a correlated per-call record to JSONL and, when configured, Postgres. Grafana reads the Postgres records. CI verifies Langfuse ingestion, Postgres writes and Grafana provisioning.

The live browser demo is not yet fully wired into this path. It still needs a trace ID per session, application Prometheus metrics and structured Loki log shipping. Until then, the observability stack is benchmark-ready and infrastructure-tested—not complete production telemetry.

## Data rules

- Never add customer call recordings without explicit rights, consent and de-identification.
- Freeze or cache generated audio before comparing models; per-run synthesis variation can invalidate a ranking.
- Keep raw hypotheses for ASR scoring even when domain normalization improves the displayed transcript.
- Do not tune thresholds on the held-out test set.
- Publish failures and uncertainty, not only averages.
