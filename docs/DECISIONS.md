# DECISIONS.md — Duet engineering journal

Every non-trivial choice gets a dated entry: what was decided, the alternatives, and why.
Running project spend is tracked at the bottom. This file is a deliverable, not an afterthought.

---

## 0001 — 2026-07-05 — Repo scaffold, license, structure

**Decided:** Public repo `duet`, Apache-2.0, structure `/agent`, `/eval`, `/infra`, `/web-demo`, `/docs`.

**Why Apache 2.0:** matches Sesame CSM's license, is the most adoption-friendly choice for a project whose explicit goal is that other companies (Bolna, Giga-style teams) integrate it, and includes an express patent grant — which MIT lacks and which matters for corporate adopters.

**Name:** keeping **Duet** as the working name. Alternatives considered, for the record: **Sidetone** (the telephony term for hearing your own voice while speaking — literally what full-duplex means), **Crosstalk**, and **Barge** (from "barge-in," the industry term for user interruption). Sidetone is the strongest alternative if Duet collides with an existing product later. Not blocking on this.

---

## 0002 — 2026-07-05 — Open-source stack lock + license verification

**Decided:** adopt the mandated OSS-first stack. Licenses verified via the GitHub API on 2026-07-05 (the brief was right to ask — two components turned out to be dead):

| Component | Role | License (verified) | Notes |
|---|---|---|---|
| Langfuse | LLM tracing/cost per call | `NOASSERTION` on GitHub — core is **MIT**, `/ee` folders are commercial | Self-hosting the OSS core is explicitly permitted; we use no `/ee` features |
| LiveKit OSS | WebRTC SFU | Apache-2.0 | Self-hosted server, not LiveKit Cloud |
| Prometheus | Metrics | Apache-2.0 | |
| Grafana | Dashboards + alerting | **AGPL-3.0** | Fine: AGPL obligations trigger on modification+network service; we run it unmodified as an internal tool. Documented so adopters know. |
| Loki | Logs | AGPL-3.0 | Same reasoning |
| k6 | Load testing | AGPL-3.0 | Dev-time tool only, never shipped |
| faster-whisper | Baseline ASR | MIT | |
| Piper | Baseline TTS | ⚠️ `rhasspy/piper` is **archived**; successor `OHF-Voice/piper1-gpl` is **GPL-3.0** | Acceptable: invoked as a separate process in the *eval baseline only* — never linked into Duet's Apache code. Fallback: Kokoro TTS (Apache-2.0). |
| Caddy | Reverse proxy/TLS | Apache-2.0 | |
| Postgres | DB (leads, audit log, metrics) | PostgreSQL License | |
| Listmonk | (future) mailing list | AGPL-3.0 | Not deployed in v1 |
| Moshi (Kyutai) | candidate duplex core | Apache-2.0 (code); weights CC-BY-4.0 | See 0003 |
| CSM-1B (Sesame) | candidate duplex core | Apache-2.0 | See 0003 |

**⚠️ Deviation flag — MinIO:** `minio/minio` is **archived on GitHub**. MinIO effectively ended its open-source community edition in 2025 (features stripped, then the repo frozen). Adopting an archived dependency in a project pitched on "no vendor lock-in" would be self-defeating. **Proposal:** for v1 demo scale, store recordings on a plain Docker volume with paths + retention tracked in Postgres; if/when S3-compatible storage is genuinely needed (Phase 4), use **SeaweedFS (Apache-2.0)** or **Garage (AGPL-3.0)** instead. Flagged here per the brief before switching. *(Also noted: Coqui TTS the company shut down in 2024; its code lives on as a community fork under MPL-2.0, but Piper/Kokoro are the healthier baseline choices.)*

**Alternatives considered:** paid SaaS at each layer (Datadog, LiveKit Cloud, S3, Mailchimp) — rejected per cost guardrails and because self-hostability *is the pitch*.

---

## 0003 — 2026-07-05 — ⚠️ ARCHITECTURAL FORK (awaiting user decision): the duplex core — CSM vs. Moshi

This is the load-bearing decision of the whole project, and the brief's default ("lean CSM") hides a trap that has to be surfaced honestly.

**The trap: CSM-1B is not a full-duplex model.** Sesame's open-sourced CSM-1B is a *conversational speech generation* model — a context-aware TTS. It takes conversation history (text + audio) and produces expressive speech. It has **no listening path while speaking**; it cannot backchannel or detect interruptions natively. Sesame's famous demo wraps CSM in additional (closed) orchestration. Building "full-duplex Duet" on CSM alone means we'd be hand-engineering duplex behavior (VAD, streaming ASR, barge-in logic) around a TTS — i.e., building a *better cascade*, which is exactly the architecture this project exists to leapfrog.

**Moshi (Kyutai) is the only production-grade open model that is natively full-duplex.** It models **two audio streams simultaneously** — the user's and its own — as parallel token streams over the Mimi streaming codec (12.5 Hz frames, ~80ms), plus an "inner monologue" text stream. There are no turns in the architecture at all: interruption handling and backchanneling are emergent, not engineered. Theoretical latency ~160-200ms. Apache-2.0 code, CC-BY-4.0 weights, and — critically for our cost guardrails — Kyutai ships an official **MLX backend (`moshi_mlx`)** with 4/8-bit quantization that runs on Apple Silicon, and an official `moshi-rag` example of exactly the async-augmentation pattern Phase 2 requires.

**Trade-offs, honestly stated:**

| | Moshi | CSM-1B |
|---|---|---|
| Natively full-duplex | ✅ the whole point | ❌ generation-only |
| Fits M-series 16GB via MLX | ✅ official backend, ~4-8GB quantized | ✅ community MLX ports |
| Voice quality/expressiveness | Decent, slightly robotic | ✅ excellent |
| Steerability/intelligence | ⚠️ weak — rambles, hard to keep on-script (this is *why* Phase 2's async reasoning layer exists) | N/A (intelligence comes from whatever LLM you pair it with) |
| Persona/voice control | Limited | ✅ strong |
| Ecosystem fit | `moshi-rag` = our Phase 2 pattern, first-party | No duplex tooling |

**Recommendation:** **Moshi as the duplex core.** The concrete reason the brief asked for: CSM cannot do the one thing the project is named after. CSM remains on the bench for a possible future role (higher-quality voice for the *baseline*, or a "CSM-cascade-plus" middle configuration in the benchmark).

**Also evaluated:** Kyutai's *Unmute* (2025) — a cascaded-but-smart stack (streaming STT + semantic VAD + streaming TTS) that fakes duplex well. Rejected as the core (it's still a cascade) but it's a strong candidate for making our Phase 3 *baseline* state-of-the-art-fair rather than a strawman.

**Status: PROPOSED — do not build Phase 1 until the user confirms.** Cost impact: none (both run locally on the Mac).

---

## Running spend

| Date | Item | Cost | Total |
|---|---|---|---|
| 2026-07-05 | Phase 0 (scaffold, GitHub, license checks) | $0.00 | **$0.00** |

Ask-before-spend threshold: **$20** per the brief's cost guardrails.
