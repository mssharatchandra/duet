# Duet Phase 2 — the async reasoning layer ("slow brain, fast mouth").
#
# The moshi-rag pattern: the duplex core NEVER waits for this module. A call
# here runs on a daemon thread; whenever a result lands, the conversation loop
# picks it up on a later 80 ms frame and injects it (injector.py). If Gemini
# is slow, errors out, or times out, nothing stalls — Moshi keeps holding the
# conversation on its own, which IS the graceful-degradation behavior: the
# lead hears a chatty agent, not dead air. Guidance that arrives after the
# topic moved on is dropped by the injector's barge-in/staleness rules.
#
# Pure stdlib on purpose (urllib, threading): no SDK pin, no event loop to
# fight with the audio loop, trivially testable with a fake transport.

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import persona

DEFAULT_MODEL = "gemini-3.1-flash-lite"  # measured ~1.0 s round-trip (DECISIONS.md 0005)
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# $ per 1M tokens (input, output). ESTIMATES for reporting — dev usage rides
# the free tier; re-verify against ai.google.dev/pricing before publishing
# the Phase 3 cost benchmark.
PRICE_PER_M = {
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-3.5-flash": (0.30, 2.50),
}


@dataclass
class Guidance:
    intent: str
    objection_type: str | None
    talking_point: str
    lead_signals: dict
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ReasoningFailure:
    reason: str
    latency_ms: float = 0.0


@dataclass
class UsageStats:
    calls: int = 0
    failures: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latencies_ms: list = field(default_factory=list)

    def cost_usd(self, model: str) -> float:
        pin, pout = PRICE_PER_M.get(model, (0.0, 0.0))
        return (self.tokens_in * pin + self.tokens_out * pout) / 1e6


def parse_guidance(response: dict) -> Guidance:
    """Parse a generateContent response into validated Guidance.

    Model output is external input — validate at the boundary: bad intent
    labels are coerced to 'other', signals to 'none', and a missing
    talking_point raises (the caller turns that into ReasoningFailure).
    """
    text = response["candidates"][0]["content"]["parts"][0]["text"]
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(text)

    intent = data.get("intent") if data.get("intent") in persona.INTENTS else "other"
    objection = data.get("objection_type")
    if objection not in persona.OBJECTION_PLAYBOOK:
        objection = None
    talking_point = str(data["talking_point"]).strip()
    if not talking_point:
        raise ValueError("empty talking_point")
    signals = {
        dim: (data.get("lead_signals", {}).get(dim) if data.get("lead_signals", {}).get(dim) in persona.SIGNAL_STRENGTHS else "none")
        for dim in persona.BANT
    }
    usage = response.get("usageMetadata", {})
    return Guidance(
        intent=intent,
        objection_type=objection,
        talking_point=talking_point,
        lead_signals=signals,
        tokens_in=usage.get("promptTokenCount", 0),
        tokens_out=usage.get("candidatesTokenCount", 0),
    )


class ReasoningLayer:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout_s: float = 6.0):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set (see .env.example)")
        self.model = model or os.environ.get("REASONING_MODEL", DEFAULT_MODEL)
        self.timeout_s = timeout_s
        self.results: queue.Queue = queue.Queue()
        self.stats = UsageStats()
        # Optional Langfuse tracing (Phase 3): set both to trace every call.
        self.tracer = None
        self.trace_id: str | None = None

    # -- the non-blocking API the conversation loop uses --------------------

    def request(self, history: list[tuple[str, str]], user_utterance: str) -> None:
        """Fire and forget. Result (Guidance | ReasoningFailure) appears in self.results."""
        threading.Thread(target=self._call, args=(history, user_utterance), daemon=True).start()

    def poll(self):
        """Non-blocking check the loop makes once per frame. None = nothing yet."""
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    # -- transport -----------------------------------------------------------

    def _call(self, history, user_utterance) -> None:
        t0 = time.perf_counter()
        t_wall = time.time()
        self.stats.calls += 1
        try:
            response = self._post(persona.build_prompt(history, user_utterance))
            guidance = parse_guidance(response)
            guidance.latency_ms = (time.perf_counter() - t0) * 1e3
            self.stats.tokens_in += guidance.tokens_in
            self.stats.tokens_out += guidance.tokens_out
            self.stats.latencies_ms.append(guidance.latency_ms)
            if self.tracer and self.trace_id:
                self.tracer.generation(self.trace_id, "reasoning", self.model, user_utterance,
                                       guidance.talking_point, guidance.tokens_in, guidance.tokens_out,
                                       t_wall - guidance.latency_ms / 1e3, t_wall)
            self.results.put(guidance)
        except Exception as e:  # any failure degrades gracefully, never propagates
            self.stats.failures += 1
            failure = ReasoningFailure(reason=f"{type(e).__name__}: {e}", latency_ms=(time.perf_counter() - t0) * 1e3)
            if self.tracer and self.trace_id:
                self.tracer.generation(self.trace_id, "reasoning", self.model, user_utterance,
                                       failure.reason, 0, 0, t_wall - failure.latency_ms / 1e3, t_wall, error=True)
            self.results.put(failure)

    def _post(self, prompt: str) -> dict:
        generation_config: dict = {"maxOutputTokens": 500, "responseMimeType": "application/json"}
        if "lite" not in self.model:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}  # voice can't wait for thinking
        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": persona.SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
            }
        ).encode()
        req = urllib.request.Request(
            f"{API_ROOT}/{self.model}:generateContent",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.load(resp)
