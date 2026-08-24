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
from .actions import ActionRequest, parse_action_request, parse_action_requests
from .rate_limits import ProviderQuota, gemini_quota

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
    conversation_stage: str = "discovery"
    response_strategy: str = "acknowledge_and_answer"
    next_action: str = "continue"
    fact_ids: list[str] = field(default_factory=list)
    decision_summary: str = "Answer from verified project facts."
    lead_evidence: dict = field(default_factory=dict)
    tool_request: ActionRequest | None = None
    tool_requests: list[ActionRequest] = field(default_factory=list)
    request_id: int = 0
    user_utterance: str = ""
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ReasoningFailure:
    reason: str
    latency_ms: float = 0.0
    request_id: int = 0
    user_utterance: str = ""


@dataclass
class SpeechPreview:
    """A complete spoken field decoded before the rest of streamed metadata."""

    request_id: int
    user_utterance: str
    text: str
    latency_ms: float


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


class DeterministicDemoBrain:
    """Offline, zero-quota ASBL planner for a reliable live demonstration.

    This is deliberately *not* presented as an LLM replacement.  It is the
    failure-safe policy lane used when a live recording cannot depend on an
    upstream model quota.  It implements the same small non-blocking contract
    as :class:`ReasoningLayer`, so the audio, barge-in, policy, action and
    telemetry paths remain exactly the paths used with Gemini.
    """

    model = "local-asbl-demo-policy"

    def __init__(self):
        self.results: queue.Queue = queue.Queue()
        self.previews: queue.Queue = queue.Queue()
        self.stats = UsageStats()
        self.tracer = None
        self.trace_id: str | None = None
        self._request_lock = threading.Lock()
        self._request_seq = 0

    def request(self, history: list[tuple[str, str]], user_utterance: str) -> int:
        """Plan synchronously, expose it asynchronously through ``poll``.

        The response is put on a queue rather than returned so every caller
        continues to use the production non-blocking interface.  No speech
        preview is issued: final ASR remains the source of truth in this
        deterministic recording mode.
        """
        del history  # Future policy versions may use compact, explicit state.
        with self._request_lock:
            self._request_seq += 1
            request_id = self._request_seq
        started = time.perf_counter()
        guidance = _demo_guidance(user_utterance)
        guidance.request_id = request_id
        guidance.user_utterance = user_utterance
        guidance.latency_ms = (time.perf_counter() - started) * 1e3
        self.stats.calls += 1
        self.stats.latencies_ms.append(guidance.latency_ms)
        self.results.put(guidance)
        return request_id

    def poll(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def poll_preview(self):
        return None


def _demo_guidance(user_utterance: str) -> Guidance:
    """Return a compact, fact-grounded ASBL answer without network inference.

    The matching is intentionally narrow and auditable.  Unknown questions
    are clarified rather than guessed, which makes this a better on-stage
    fallback than a generic hallucination-prone response.
    """
    text = user_utterance.lower()
    signals = {dimension: "none" for dimension in persona.BANT}
    evidence = {dimension: None for dimension in persona.BANT}

    def answer(
        spoken: str,
        *,
        intent: str = "question",
        facts: list[str] | None = None,
        stage: str = "education",
        strategy: str = "acknowledge_and_answer",
        next_action: str = "ask",
        objection: str | None = None,
    ) -> Guidance:
        return Guidance(
            intent=intent,
            objection_type=objection,
            talking_point=spoken,
            lead_signals=signals,
            conversation_stage=stage,
            response_strategy=strategy,
            next_action=next_action,
            fact_ids=facts or [],
            decision_summary="Local grounded ASBL demo policy selected this response.",
            lead_evidence=evidence,
        )

    if any(word in text for word in ("price", "cost", "budget", "payment", "afford")):
        signals["budget_fit"] = "weak"
        evidence["budget_fit"] = "Asked about pricing or budget."
        return answer(
            "Broadway's published starting price is around three crore. Final pricing, inventory and floor premiums vary, so an authorised advisor should confirm the exact option.",
            facts=["price"], strategy="factual_boundary", objection="price",
        )
    if any(word in text for word in ("privacy", "foyer", "opposite door", "private")):
        return answer(
            "Privacy is a clear Broadway design choice: many homes have private foyers, and the planning is intended to avoid opposite main doors. Is that important for your family?",
            facts=["privacy"], strategy="explain_value",
        )
    if any(word in text for word in ("family", "live", "living", "home for us", "children", "kid")):
        signals["use_case"] = "strong"
        evidence["use_case"] = "Explicit family-home preference."
        return answer(
            "For a family home, I would compare privacy, the 3 and 3.5 BHK layouts, and everyday convenience. Which matters most to you: space, work-life amenities, or location?",
            intent="discovery_answer", facts=["homes", "privacy", "amenities"], stage="discovery", strategy="clarify_need",
        )
    if any(word in text for word in ("investment", "invest", "yield", "return", "appreciation", "rental", "rent")):
        signals["use_case"] = "strong"
        evidence["use_case"] = "Explicit investment use case."
        return answer(
            "Broadway is in the Financial District, but I would not promise rental yield or appreciation. I can help compare verified location, layout and possession facts against your investment horizon.",
            intent="objection", facts=["location", "possession"], strategy="factual_boundary", objection="investment_returns",
        )
    if any(word in text for word in ("location", "commute", "orr", "gachibowli", "financial district", "office")):
        return answer(
            "Broadway is in Hyderabad's Financial District, beside ASBL Loft, with access toward Gachibowli and the ORR corridor. Which workplace or commute would you want to evaluate?",
            facts=["location"], strategy="clarify_need",
        )
    if any(word in text for word in ("possession", "handover", "ready", "move", "timeline", "when")):
        signals["timeline"] = "weak"
        evidence["timeline"] = "Asked about timing or possession."
        return answer(
            "The published possession date is December 2029. Does that horizon work for you, or are you looking for a home sooner?",
            facts=["possession"], strategy="factual_boundary", objection="timing",
        )
    if any(word in text for word in ("bhk", "bedroom", "layout", "size", "square", "sq")):
        return answer(
            "Broadway offers 3 and 3.5 BHK homes, with published super built-up sizes from 2,035 to 2,650 square feet. Would you like to compare the family-use cases for the two layouts?",
            facts=["homes"], strategy="explain_value",
        )
    if any(word in text for word in ("amenity", "club", "cowork", "work from home", "creche", "gym", "pool")):
        return answer(
            "Broadway publishes more than 107,000 square feet of indoor amenities, including practical work-life spaces. Would co-working, fitness, or family recreation be most useful to you?",
            facts=["amenities"], strategy="explain_value",
        )
    if any(word in text for word in ("light", "height", "ceiling", "ventilation", "curtain wall")):
        return answer(
            "The design uses curtain-wall elements for natural light, and the keynote specifies 3,300 millimetres slab-to-slab height. Would you like to compare that feeling of space with privacy or layout?",
            facts=["light_and_height"], strategy="explain_value",
        )
    if any(word in text for word in ("brochure", "callback", "call me", "site visit", "visit")):
        action_name = "send_brochure" if "brochure" in text else ("book_site_visit" if "visit" in text else "schedule_callback")
        request = ActionRequest(action_name, {"project": "ASBL Broadway"})
        return Guidance(
            intent="site_visit" if action_name == "book_site_visit" else "callback",
            objection_type=None,
            talking_point="Certainly. I am putting that request through now.",
            lead_signals=signals,
            conversation_stage="next_step",
            response_strategy="offer_next_step",
            next_action="tool",
            decision_summary="Local demo policy recognised an explicit ASBL action request.",
            lead_evidence=evidence,
            tool_request=request,
            tool_requests=[request],
        )
    return answer(
        "I can help you compare Broadway on privacy, layouts, Financial District location, amenities, published pricing, or possession. Which would be most useful right now?",
        intent="discovery_answer", stage="discovery", strategy="clarify_need",
    )


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
    strategy = data.get("response_strategy")
    if strategy not in persona.RESPONSE_STRATEGIES:
        strategy = "acknowledge_and_answer"
    talking_point = str(data["talking_point"]).strip()
    if not talking_point and strategy != "wait":
        raise ValueError("empty talking_point")
    signals = {
        dim: (data.get("lead_signals", {}).get(dim) if data.get("lead_signals", {}).get(dim) in persona.SIGNAL_STRENGTHS else "none")
        for dim in persona.BANT
    }
    stage = data.get("conversation_stage")
    if stage not in persona.CONVERSATION_STAGES:
        stage = "discovery"
    next_action = data.get("next_action")
    if next_action not in persona.NEXT_ACTIONS:
        next_action = "continue"
    fact_ids = list(dict.fromkeys(
        fact_id for fact_id in data.get("fact_ids", []) if fact_id in persona.FACT_REGISTRY
    ))[:3]
    evidence = {
        dim: (str(data.get("lead_evidence", {}).get(dim)).strip()[:100]
              if data.get("lead_evidence", {}).get(dim) else None)
        for dim in persona.BANT
    }
    decision_summary = str(data.get("decision_summary", "Answer from verified project facts.")).strip()
    if not decision_summary:
        decision_summary = "Answer from verified project facts."
    tool_requests = parse_action_requests(data.get("tool_requests"))
    legacy_tool = parse_action_request(data.get("tool_request"))
    if legacy_tool is not None and all(item.name != legacy_tool.name for item in tool_requests):
        tool_requests.append(legacy_tool)
    tool_request = tool_requests[0] if tool_requests else None
    usage = response.get("usageMetadata", {})
    return Guidance(
        intent=intent,
        objection_type=objection,
        talking_point=talking_point,
        lead_signals=signals,
        conversation_stage=stage,
        response_strategy=strategy,
        next_action=next_action,
        fact_ids=fact_ids,
        decision_summary=" ".join(decision_summary.split()[:14]),
        lead_evidence=evidence,
        tool_request=tool_request,
        tool_requests=tool_requests,
        tokens_in=usage.get("promptTokenCount", 0),
        tokens_out=usage.get("candidatesTokenCount", 0),
    )


class ReasoningLayer:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float = 6.0,
        *,
        system_prompt: str | None = None,
        prompt_builder=None,
        response_parser=None,
        quota: ProviderQuota | None = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set (see .env.example)")
        self.model = model or os.environ.get("REASONING_MODEL", DEFAULT_MODEL)
        self.timeout_s = timeout_s
        # Keep transport generic enough for alternate sales planners without
        # coupling provider I/O to a particular response schema.
        self.system_prompt = system_prompt or persona.SYSTEM_PROMPT
        self.prompt_builder = prompt_builder or persona.build_prompt
        self.response_parser = response_parser or parse_guidance
        self.quota = quota or gemini_quota()
        self.results: queue.Queue = queue.Queue()
        self.previews: queue.Queue = queue.Queue()
        self.stats = UsageStats()
        self._request_lock = threading.Lock()
        self._request_seq = 0
        self._request_context = threading.local()
        # Optional Langfuse tracing (Phase 3): set both to trace every call.
        self.tracer = None
        self.trace_id: str | None = None

    # -- the non-blocking API the conversation loop uses --------------------

    def request(self, history: list[tuple[str, str]], user_utterance: str) -> int:
        """Fire and forget. Result (Guidance | ReasoningFailure) appears in self.results."""
        with self._request_lock:
            self._request_seq += 1
            request_id = self._request_seq
        threading.Thread(target=self._call, args=(history, user_utterance, request_id), daemon=True).start()
        return request_id

    def poll(self):
        """Non-blocking check the loop makes once per frame. None = nothing yet."""
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def poll_preview(self):
        try:
            return self.previews.get_nowait()
        except queue.Empty:
            return None

    # -- transport -----------------------------------------------------------

    def _call(self, history, user_utterance, request_id: int = 0) -> None:
        t0 = time.perf_counter()
        t_wall = time.time()
        self.stats.calls += 1
        try:
            self._request_context.request_id = request_id
            self._request_context.user_utterance = user_utterance
            self._request_context.started_at = t0
            # Quota waiting is forbidden on the conversational path. If the
            # budget is unavailable, this raises immediately and the normal
            # ReasoningFailure path lets the deterministic controller recover.
            with self.quota.slot():
                response = self._post(self.prompt_builder(history, user_utterance))
            guidance = self.response_parser(response)
            # Custom profiles use their own result dataclasses; attach public
            # request metadata when possible without coupling their schema.
            guidance.request_id = request_id
            guidance.user_utterance = user_utterance
            guidance.latency_ms = (time.perf_counter() - t0) * 1e3
            self.stats.tokens_in += guidance.tokens_in
            self.stats.tokens_out += guidance.tokens_out
            self.stats.latencies_ms.append(guidance.latency_ms)
            if self.tracer and self.trace_id:
                output_text = getattr(guidance, "talking_point", getattr(guidance, "feedback", ""))
                self.tracer.generation(self.trace_id, "reasoning", self.model, user_utterance,
                                       output_text, guidance.tokens_in, guidance.tokens_out,
                                       t_wall - guidance.latency_ms / 1e3, t_wall)
            self.results.put(guidance)
        except Exception as e:  # noqa: BLE001 -- any provider/parser failure degrades gracefully
            self.stats.failures += 1
            failure = ReasoningFailure(
                reason=f"{type(e).__name__}: {e}",
                latency_ms=(time.perf_counter() - t0) * 1e3,
                request_id=request_id,
                user_utterance=user_utterance,
            )
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
                "systemInstruction": {"parts": [{"text": self.system_prompt}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
            }
        ).encode()
        streaming = os.environ.get("GEMINI_STREAMING", "true").lower() not in {"0", "false", "no"}
        req = urllib.request.Request(
            f"{API_ROOT}/{self.model}:{'streamGenerateContent?alt=sse' if streaming else 'generateContent'}",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            if not streaming:
                return json.load(resp)
            text = ""
            usage: dict = {}
            preview_sent = False
            for line in resp:
                if not line.startswith(b"data: "):
                    continue
                chunk = json.loads(line[6:])
                usage.update(chunk.get("usageMetadata", {}))
                candidates = chunk.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        text += parts[0].get("text", "")
                if not preview_sent:
                    spoken = extract_complete_json_string(text, "talking_point")
                    if spoken is not None:
                        preview_sent = True
                        self.previews.put(
                            SpeechPreview(
                                request_id=getattr(self._request_context, "request_id", 0),
                                user_utterance=getattr(self._request_context, "user_utterance", ""),
                                text=spoken.strip(),
                                latency_ms=(time.perf_counter() - self._request_context.started_at) * 1e3,
                            )
                        )
            return {
                "candidates": [{"content": {"parts": [{"text": text}]}}],
                "usageMetadata": usage,
            }


def extract_complete_json_string(text: str, key: str) -> str | None:
    """Decode one complete JSON string field from an otherwise partial stream."""
    marker = f'"{key}"'
    key_at = text.find(marker)
    if key_at < 0:
        return None
    colon = text.find(":", key_at + len(marker))
    if colon < 0:
        return None
    start = text.find('"', colon + 1)
    if start < 0:
        return None
    escaped = False
    for index in range(start + 1, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            try:
                return json.loads(text[start:index + 1])
            except json.JSONDecodeError:
                return None
    return None
