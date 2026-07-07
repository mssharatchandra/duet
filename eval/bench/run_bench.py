#!/usr/bin/env python3
# Duet Phase 3 — the head-to-head benchmark: full-duplex Duet vs cascaded baseline.
#
# Method (also in RESULTS.md — every number this prints is criticizable):
#
# A SIMULATED CALLER speaks each scenario's lines as real audio (Piper TTS).
#
# DUET side — real measurement: the caller's audio is fed into Moshi's actual
# input stream frame by frame; Moshi's decoded output audio is energy-detected
# on the same 80 ms grid. Takeovers, backchannels, handoff latency and overlap
# come out of duet_agent.turntaking applied to what the model actually did.
# One turn per scenario is a BARGE-IN: the caller starts talking while the
# agent is audibly mid-speech.
#
# CASCADE side — measured components on a simulated timeline: real
# faster-whisper ASR latency + real Gemini latency (same persona/brain as
# Duet) + real Piper synthesis latency for the reply, plus two documented
# constants a production cascade cannot avoid:
#     ENDPOINT_WAIT_S = 0.7  (silence-based endpointing delay)
#     BARGE_KILL_S    = 0.4  (time to detect barge-in and stop TTS playback)
# The cascade cannot backchannel and keeps speaking for BARGE_KILL_S after a
# barge-in, by construction — that IS the architecture being benchmarked.
#
# Outputs: out/calls.jsonl · out/clips/*.wav (mixed caller+agent audio for
# blind listening) · Postgres `calls` rows · Langfuse trace per call ·
# RESULTS.md refresh. All telemetry fail-silent (JSONL always works).

import argparse
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

from duet_agent import local_loop, telemetry, turntaking  # noqa: E402
from duet_agent.asr_util import to_whisper_rate  # noqa: E402
from duet_agent.injector import TextInjector  # noqa: E402
from duet_agent.reasoning import Guidance, ReasoningLayer  # noqa: E402

OUT = Path(__file__).parent / "out"
FRAME = local_loop.FRAME_SIZE
RATE = local_loop.SAMPLE_RATE
FRAME_S = FRAME / RATE

ENDPOINT_WAIT_S = 0.7
BARGE_KILL_S = 0.4
CALLER_GAP_S = 0.7        # thinking pause before the caller's next line (both modes)
BARGE_AFTER_S = 0.5       # barge-in starts this far into the agent's speech
RMS_USER = 0.010
RMS_AGENT = 0.015


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        import os
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------- caller TTS

_voice = None


def synth(text: str) -> np.ndarray:
    """Piper → mono float32 @ 24 kHz (linear resample from 22.05 kHz)."""
    global _voice
    if _voice is None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice
        _voice = PiperVoice.load(
            hf_hub_download("rhasspy/piper-voices", "en/en_US/lessac/medium/en_US-lessac-medium.onnx"),
            hf_hub_download("rhasspy/piper-voices", "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"),
        )
    pcm = np.concatenate([np.frombuffer(c.audio_int16_bytes, np.int16) for c in _voice.synthesize(text)])
    pcm = pcm.astype(np.float32) / 32768.0
    src_rate = _voice.config.sample_rate
    n_out = int(len(pcm) * RATE / src_rate)
    return np.interp(np.linspace(0, len(pcm) - 1, n_out), np.arange(len(pcm)), pcm).astype(np.float32)


def frames_of(pcm: np.ndarray) -> list[np.ndarray]:
    n = (len(pcm) + FRAME - 1) // FRAME
    return [np.pad(pcm[i * FRAME:(i + 1) * FRAME], (0, max(0, FRAME - len(pcm[i * FRAME:(i + 1) * FRAME]))))
            for i in range(n)]


def write_wav(path: Path, pcm: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- duet mode

def run_duet(scenario: dict, tracer, args) -> dict:
    import huggingface_hub
    import mlx.core as mx
    import rustymimi

    injector: TextInjector | None = None

    def hook(text_tokens):
        if injector is None:
            return
        sampled = int(text_tokens[0, 0].item())
        forced = injector.hook(sampled)
        if forced != sampled:
            text_tokens[:] = mx.array([[forced]], dtype=text_tokens.dtype)

    gen, tok, _ = local_loop.load_model(args, on_text_hook=hook)
    injector = TextInjector(encode=lambda s: list(tok.encode(s)))  # type: ignore
    codec = rustymimi.StreamTokenizer(
        huggingface_hub.hf_hub_download(args.hf_repo, "tokenizer-e351c8d8-checkpoint125.safetensors"))  # type: ignore

    trace_id = tracer.trace("duet-call", {"mode": "duet", "scenario": scenario["id"]})
    brain = ReasoningLayer()
    brain.tracer, brain.trace_id = tracer, trace_id

    turns = list(scenario["turns"])
    turn_frames: list[np.ndarray] = []            # caller audio queue, frame granularity
    user_active: list[bool] = []
    agent_active: list[bool] = []
    caller_track: list[np.ndarray] = []
    agent_track: list[np.ndarray] = []
    history: list[tuple[str, str]] = []
    silence = np.zeros(FRAME, np.float32)

    agent_run = 0          # consecutive agent-active frames (for barge timing)
    agent_quiet = 0        # consecutive agent-quiet frames (for next-turn timing)
    answered = True        # agent has responded since last caller turn
    wait_since_turn = 0.0
    max_frames = min(args.steps - 10, int(len(turns) * 11 / FRAME_S / len(turns) * len(turns) + 250))
    t_start = time.perf_counter()

    frame = 0
    while frame < args.steps - 10:
        t = frame * FRAME_S
        # schedule next caller turn
        if turns and not turn_frames:
            barge = turns[0].get("barge", False)
            due = (
                (frame == 12) if not history else (
                    (agent_run >= round(BARGE_AFTER_S / FRAME_S)) if barge
                    else (answered and agent_quiet >= round(CALLER_GAP_S / FRAME_S))
                )
            )
            if due or (history and t - wait_since_turn > 10.0):
                turn = turns.pop(0)
                turn_frames = frames_of(synth(turn["text"]))
                brain.request(history, turn["text"])
                history.append(("lead", turn["text"]))
                answered = False
                wait_since_turn = t

        result = brain.poll()
        if isinstance(result, Guidance):
            injector.inject(result.talking_point)
            history.append(("agent", result.talking_point))

        user_frame = turn_frames.pop(0) if turn_frames else silence
        u_rms = float(np.sqrt(np.mean(user_frame**2)))
        injector.on_user_frame(u_rms)
        caller_track.append(user_frame)
        user_active.append(u_rms > RMS_USER)

        codec.encode(user_frame)
        deadline = time.time() + 30  # generous: system sleep must not kill a run
        while (data := codec.get_encoded()) is None:
            if time.time() > deadline:
                raise RuntimeError("encoder stalled")
            time.sleep(0.001)
        audio_out, _piece = local_loop.step_once(gen, tok, data)
        a_pcm = silence
        if audio_out is not None:
            codec.decode(audio_out)
            got = codec.get_decoded()
            for _ in range(200):
                if got is not None:
                    break
                time.sleep(0.001)
                got = codec.get_decoded()
            if got is not None:
                a_pcm = np.asarray(got, np.float32)[:FRAME]
        a_rms = float(np.sqrt(np.mean(a_pcm**2)))
        agent_track.append(a_pcm)
        active = a_rms > RMS_AGENT
        agent_active.append(active)
        agent_run = agent_run + 1 if active else 0
        agent_quiet = agent_quiet + 1 if not active else 0
        if active and not answered and not turn_frames:
            answered = True

        frame += 1
        if not turns and not turn_frames and answered and agent_quiet >= round(1.6 / FRAME_S):
            break
        if frame >= max_frames + 800:
            break

    gpu_seconds = time.perf_counter() - t_start
    n = min(len(caller_track), len(agent_track))
    mixed = np.concatenate(caller_track[:n]) + np.concatenate(agent_track[:n])
    write_wav(OUT / "clips" / f"duet-{scenario['id']}.wav", mixed)

    report = turntaking.analyze(user_active, agent_active)
    return _record(scenario, "duet", report, frame * FRAME_S, gpu_seconds, brain, trace_id)


# ------------------------------------------------------------- cascade mode

_asr = None


def run_cascade(scenario: dict, tracer, args) -> dict:
    global _asr
    if _asr is None:
        from faster_whisper import WhisperModel
        _asr = WhisperModel("base.en", device="cpu", compute_type="int8")

    trace_id = tracer.trace("cascade-call", {"mode": "cascade", "scenario": scenario["id"]})
    brain = ReasoningLayer()
    brain.tracer, brain.trace_id = tracer, trace_id
    history: list[tuple[str, str]] = []

    # events on a simulated timeline: (start_s, pcm, who)
    events: list[tuple[float, np.ndarray, str]] = []
    t = 1.0
    prev_agent_start, prev_agent_pcm = None, None

    for turn in scenario["turns"]:
        user_pcm = synth(turn["text"])
        user_dur = len(user_pcm) / RATE
        if turn.get("barge") and prev_agent_start is not None:
            u_start = prev_agent_start + BARGE_AFTER_S
            # cascade keeps talking BARGE_KILL_S after the barge, then cuts
            cut = u_start + BARGE_KILL_S - prev_agent_start
            events[-1] = (prev_agent_start, prev_agent_pcm[: int(cut * RATE)], "agent")
        else:
            u_start = t + CALLER_GAP_S
        events.append((u_start, user_pcm, "user"))
        u_end = u_start + user_dur

        t0 = time.perf_counter()
        segments, _ = _asr.transcribe(to_whisper_rate(user_pcm), language="en", beam_size=1)
        asr_text = " ".join(s.text.strip() for s in segments).strip() or turn["text"]
        asr_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        brain._call(history, asr_text)
        result = brain.results.get()
        llm_s = time.perf_counter() - t0
        reply = result.talking_point if isinstance(result, Guidance) else "Sorry, could you repeat that?"
        history += [("lead", asr_text), ("agent", reply)]

        t0 = time.perf_counter()
        agent_pcm = synth(reply)
        tts_s = time.perf_counter() - t0

        a_start = u_end + ENDPOINT_WAIT_S + asr_s + llm_s + tts_s
        events.append((a_start, agent_pcm, "agent"))
        prev_agent_start, prev_agent_pcm = a_start, agent_pcm
        t = a_start + len(agent_pcm) / RATE

    total_s = t + 1.0
    grid = int(total_s / FRAME_S) + 1
    user_active = [False] * grid
    agent_active = [False] * grid
    mixed = np.zeros(int(total_s * RATE) + RATE, np.float32)
    for start, pcm, who in events:
        i0 = int(start * RATE)
        mixed[i0:i0 + len(pcm)] += pcm
        track = user_active if who == "user" else agent_active
        for f in range(int(start / FRAME_S), min(int((start + len(pcm) / RATE) / FRAME_S) + 1, grid)):
            track[f] = True
    write_wav(OUT / "clips" / f"cascade-{scenario['id']}.wav", mixed)

    report = turntaking.analyze(user_active, agent_active)
    return _record(scenario, "cascade", report, total_s, 0.0, brain, trace_id)


# ------------------------------------------------------------------ common

def _record(scenario, mode, report, duration_s, gpu_seconds, brain, trace_id) -> dict:
    rec = {
        "call_id": f"{mode}-{scenario['id']}-{int(time.time())}",
        "mode": mode,
        "scenario": scenario["id"],
        "duration_s": round(duration_s, 2),
        "gpu_seconds": round(gpu_seconds, 2),
        "tokens_in": brain.stats.tokens_in,
        "tokens_out": brain.stats.tokens_out,
        "langfuse_trace_id": trace_id,
        **report.summary(),
        **telemetry.cost_fields(gpu_seconds, brain.stats.cost_usd(brain.model), duration_s),
        "_handoffs_ms": [round(h, 1) for h in report.handoff_ms],
    }
    return rec


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="duet,cascade")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N scenarios")
    ap.add_argument("-q", "--quantized", type=int, default=4, choices=[4, 8])
    ap.add_argument("--hf-repo", default=None)
    ap.add_argument("--steps", type=int, default=4000)
    args = ap.parse_args()
    if args.hf_repo is None:
        args.hf_repo = local_loop.DEFAULT_REPOS[args.quantized]

    scenarios = json.loads((Path(__file__).parent / "scenarios.json").read_text())
    if args.limit:
        scenarios = scenarios[: args.limit]
    tracer = telemetry.LangfuseTracer()
    store = telemetry.CallStore()
    OUT.mkdir(parents=True, exist_ok=True)

    records = []
    for mode in args.modes.split(","):
        runner = run_duet if mode == "duet" else run_cascade
        for sc in scenarios:
            t0 = time.time()
            rec = runner(sc, tracer, args)
            records.append(rec)
            store.insert({k: v for k, v in rec.items() if not k.startswith("_")})
            with open(OUT / "calls.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"[{mode}] {sc['id']}: takeover={rec['takeover_rate']:.2f}"
                  f" handoff_p50={rec['response_latency_ms_p50']}ms"
                  f" overlap={rec['overlap_ratio']:.3f} ({time.time() - t0:.0f}s wall)")

    # summary across this run
    print("\n===== summary =====")
    lines = ["| mode | calls | takeover rate | backchannels/call | handoff p50 | handoff p95 | overlap | $/min |",
             "|---|---|---|---|---|---|---|---|"]
    for mode in args.modes.split(","):
        rs = [r for r in records if r["mode"] == mode]
        if not rs:
            continue
        hand = [h for r in rs for h in r["_handoffs_ms"]]
        row = (f"| {mode} | {len(rs)} | {np.mean([r['takeover_rate'] for r in rs]):.2f} "
               f"| {np.mean([r['backchannels'] for r in rs]):.1f} "
               f"| {np.percentile(hand, 50):.0f} ms | {np.percentile(hand, 95):.0f} ms "
               f"| {np.mean([r['overlap_ratio'] for r in rs]):.3f} "
               f"| ${np.mean([r['cost_per_min_usd'] for r in rs]):.4f} |")
        lines.append(row)
    table = "\n".join(lines)
    print(table)
    (OUT / "summary.md").write_text(table + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
