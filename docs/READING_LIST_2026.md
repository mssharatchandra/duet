# Current voice-AI reading list

Checked 23 August 2026. Read in this order. Primary sources and official engineering documentation dominate;
vendor posts are useful for architecture patterns but not neutral evidence of comparative quality.

## Start with systems reality

1. [How OpenAI built a realtime system for responsive voice AI in six months](https://openai.com/index/continuous-voice-interaction-with-gpt-live/) — August 2026. The closest public description of the architecture Duet is moving toward: a dedicated continuous media path, stateful voice inference, asynchronous delegation, speculative versus authoritative conversation views, shadow traffic and regional/session-capacity testing.
2. [How OpenAI delivers low-latency voice AI at scale](https://openai.com/index/delivering-low-latency-voice-ai-at-scale/) — May 2026. Read for WebRTC, global routing, session stickiness, packet/jitter concerns and why model latency is only one part of responsiveness.
3. [LiveKit: turns overview](https://docs.livekit.io/agents/logic/turns/) and [turn-taking tuning](https://docs.livekit.io/agents/logic/turns/tuning/) — living documentation. Concrete distinction among VAD, endpointing, semantic turn detection, adaptive interruption, false-interruption recovery and preemptive generation.
4. [Sarvam Pipecat production guide](https://docs.sarvam.ai/api/integration/pipecat-production-guide) and [Bulbul streaming WebSocket reference](https://docs.sarvam.ai/api-reference/text-to-speech/stream) — current provider mechanics behind Duet's Indian speech path.

## Learn what the benchmarks say

5. [$\tau$-Voice: Benchmarking Full-Duplex Voice Agents on Real-World Domains](https://arxiv.org/abs/2603.13686) — 2026. Combines tool/task correctness, full-duplex behavior and realistic audio. Its central warning is crucial: current voice agents retain far less task capability than text agents under realistic conditions, and many failures are agent behavior rather than acoustic corruption alone.
6. [Full-Duplex-Bench / ICLR 2025 paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/82f68b38747c406672f7f9f6bab86775-Paper-Conference.pdf) — systematic turn-taking metrics and user study. It reports that neither native Moshi nor a cascade automatically gets backchannels, floor cues and interruptions right.
7. [Full-Duplex-Bench code](https://github.com/DanielLin94144/Full-Duplex-Bench) — inspect executable metric definitions rather than repeating benchmark names.
8. [LiveTurn](https://openreview.net/pdf?id=JIaOGuEMET) — 2026 real-time turn-detection work. Read after you understand Duet's fixed endpoint/grace policy; ask whether an acoustic/semantic learned turn model can reduce both latency and false completion.

## Native duplex research frontier

9. [Moshi](https://arxiv.org/abs/2410.00037) — the foundational open full-duplex spoken dialogue architecture used in Duet's research arm.
10. [BayLing-Duplex](https://arxiv.org/abs/2606.14528) — 2026 single-autoregressive-LLM native duplex direction; compare its synchronized streams with Duet's modular guarded cascade.
11. [HumDial Challenge comprehensive study](https://arxiv.org/abs/2604.21406) — 2026 interruption, overlap and dynamic turn negotiation evaluation landscape.
12. [VoiceChat-TTS](https://arxiv.org/abs/2608.13831) — August 2026 continuous, streamable TTS research focused on interactive agents and interruption without resetting the synthesis cache.

## Models, quotas and observability

13. [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) — current source of truth. Limits are project/tier/model dependent and Google directs developers to AI Studio for active values. Do not copy a quota from a blog.
14. [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite) — confirms the stable low-latency text-output planner Duet uses; it is not a Live API/audio-output model.
15. [Langfuse data model](https://langfuse.com/docs/observability/data-model) and [versions/compatibility](https://langfuse.com/docs/compatibility) — learn trace/session/observation semantics and the required migration from legacy ingestion to OpenTelemetry/Langfuse v4.

## How to read critically

For each item, write four sentences:

1. the sourced mechanism or result;
2. the assumption/distribution under which it holds;
3. the strongest counterexample;
4. one Duet experiment that could reproduce or falsify it.

Do not call a model “human” because a curated audio clip sounds good. Require realistic audio, interrupted
multi-turn tasks, state-changing tools, blind raters, tail latency, failure rates and cost.
