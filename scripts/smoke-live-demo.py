#!/usr/bin/env python3
"""Real end-to-end smoke test for the running controlled-duplex demo.

This intentionally calls configured Sarvam and Gemini services. It verifies
the browser protocol, streaming ASR, reasoning, first TTS audio, and spoken
barge-in cancellation without requiring a human microphone run.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from duet_agent.env import load_repo_env  # noqa: E402
from duet_agent.tts import iter_pcm_frames, load  # noqa: E402

FRAME = 1_920
FRAME_SECONDS = FRAME / 24_000


def caller_frames(voice, text: str) -> list[np.ndarray]:
    audio = list(iter_pcm_frames(voice.synthesize_stream(text), FRAME))
    return audio + [np.zeros(FRAME, np.float32) for _ in range(12)]


async def send_audio(ws, frames: list[np.ndarray]) -> None:
    for frame in frames:
        await ws.send_bytes(frame.astype(np.float32).tobytes())
        await asyncio.sleep(FRAME_SECONDS)


async def run(url: str, timeout_s: float) -> None:
    voice = load("piper")
    opening = caller_frames(voice, "Yes, this is a good time. I can talk.")
    discovery = caller_frames(voice, "It would be a home for my family, and privacy matters most to us.")
    interruption = caller_frames(voice, "Actually wait. What is the current starting price?")
    required = {"disclosure", "permission", "you", "brain", "first_audio", "playback_cancel"}
    observed: set[str] = set()
    opening_sent = discovery_sent = interrupted = False
    interruption_started_at = None
    interruption_yield_ms = None
    send_tasks: set[asyncio.Task] = set()
    started = time.perf_counter()
    measured_turn = {
        "turn_assembly_ms": None,
        "commit_at": None,
        "brain_at": None,
        "reasoning_ms": None,
        "tts_ms": None,
    }

    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(url) as ws:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                message = await asyncio.wait_for(ws.receive(), timeout=3)
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                event = json.loads(message.data)
                event_type = event.get("type")
                state = event.get("state")
                if event_type == "duet" and "ASBL's AI assistant" in event.get("text", ""):
                    observed.add("disclosure")
                if event_type == "policy" and state == "permission_granted":
                    observed.add("permission")
                if (
                    event_type == "asr_state"
                    and state == "result"
                    and discovery_sent
                    and measured_turn["commit_at"] is None
                ):
                    measured_turn["turn_assembly_ms"] = event.get("latency_ms")
                if event_type in {"you", "brain"}:
                    observed.add(event_type)
                if event_type == "playback_cancel" and interrupted:
                    observed.add("playback_cancel")
                    if interruption_started_at is not None:
                        interruption_yield_ms = (time.perf_counter() - interruption_started_at) * 1000
                if event_type == "you" and discovery_sent and measured_turn["commit_at"] is None:
                    measured_turn["commit_at"] = time.perf_counter()
                if (
                    event_type == "brain"
                    and measured_turn["commit_at"] is not None
                    and measured_turn["brain_at"] is None
                ):
                    measured_turn["brain_at"] = time.perf_counter()
                    measured_turn["reasoning_ms"] = event.get("latency_ms")
                if event_type == "tts_state" and state == "first_audio":
                    observed.add("first_audio")
                    if measured_turn["brain_at"] is not None and measured_turn["tts_ms"] is None:
                        measured_turn["tts_ms"] = event.get("latency_ms")
                    if not opening_sent:
                        opening_sent = True
                        send_tasks.add(asyncio.create_task(send_audio(ws, opening)))
                    elif "permission" in observed and not discovery_sent:
                        discovery_sent = True
                        send_tasks.add(asyncio.create_task(send_audio(ws, discovery)))
                    elif measured_turn["tts_ms"] is not None and not interrupted:
                        interrupted = True
                        interruption_started_at = time.perf_counter()
                        send_tasks.add(asyncio.create_task(send_audio(ws, interruption)))
                if required <= observed:
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    if measured_turn["commit_at"] is not None and measured_turn["tts_ms"] is not None:
                        commit_to_audio = (
                            measured_turn["brain_at"] - measured_turn["commit_at"]
                        ) * 1000 + measured_turn["tts_ms"]
                        total = (measured_turn["turn_assembly_ms"] or 0) + commit_to_audio
                        print(
                            "MEASURE final speech end→first audio "
                            f"{total:.0f} ms = turn {measured_turn['turn_assembly_ms']} ms + "
                            f"commit→brain {(measured_turn['brain_at'] - measured_turn['commit_at']) * 1000:.0f} ms + "
                            f"TTS {measured_turn['tts_ms']} ms "
                            f"(provider reasoning {measured_turn['reasoning_ms']} ms)"
                        )
                    else:
                        printable = {
                            key: (round(value * 1000) if key.endswith("_at") and value else value)
                            for key, value in measured_turn.items()
                        }
                        print(f"MEASURE unavailable; incomplete timing markers: {printable}")
                    print(f"PASS controlled-duplex E2E in {elapsed_ms} ms: {', '.join(sorted(observed))}")
                    if interruption_yield_ms is not None:
                        print(f"MEASURE caller-audio-start→playback-cancel {interruption_yield_ms:.0f} ms")
                    for task in send_tasks:
                        task.cancel()
                    await asyncio.gather(*send_tasks, return_exceptions=True)
                    return
    missing = ", ".join(sorted(required - observed))
    raise RuntimeError(f"controlled-duplex E2E failed; missing: {missing}")


def main() -> None:
    load_repo_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8990/ws")
    parser.add_argument("--timeout", type=float, default=35)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.timeout))


if __name__ == "__main__":
    main()
