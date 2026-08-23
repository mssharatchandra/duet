import json
import time

import pytest

from duet_agent import reasoning
from duet_agent.rate_limits import ProviderQuota


def _response(payload: dict, fenced: bool = False, tokens=(100, 40)) -> dict:
    text = json.dumps(payload)
    if fenced:
        text = f"```json\n{text}\n```"
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]},
    }


GOOD = {
    "intent": "objection",
    "objection_type": "price",
    "talking_point": "That budget matters; an ASBL advisor can confirm the current price precisely.",
    "lead_signals": {"budget_fit": "weak", "decision_role": "strong", "use_case": "strong", "timeline": "none"},
}


def test_parse_guidance_happy_path():
    g = reasoning.parse_guidance(_response(GOOD))
    assert g.intent == "objection"
    assert g.objection_type == "price"
    assert g.tokens_in == 100 and g.tokens_out == 40


def test_parse_guidance_strips_markdown_fences():
    g = reasoning.parse_guidance(_response(GOOD, fenced=True))
    assert g.talking_point.startswith("That budget")


def test_parse_guidance_coerces_invalid_enums():
    bad = dict(GOOD, intent="sales_magic", objection_type="vibes", lead_signals={"budget": "HUGE"})
    g = reasoning.parse_guidance(_response(bad))
    assert g.intent == "other"
    assert g.objection_type is None
    assert g.lead_signals == {
        "budget_fit": "none",
        "decision_role": "none",
        "use_case": "none",
        "timeline": "none",
    }


def test_parse_guidance_rejects_empty_talking_point():
    with pytest.raises(ValueError, match="empty talking_point"):
        reasoning.parse_guidance(_response(dict(GOOD, talking_point="  ")))


def test_parse_guidance_exposes_safe_trace_and_allowlisted_sources():
    payload = dict(
        GOOD,
        conversation_stage="objection",
        response_strategy="handle_objection",
        next_action="ask",
        fact_ids=["price", "privacy", "not-a-fact", "price"],
        decision_summary="Answer price concern with value and a current factual boundary",
        lead_evidence={"use_case": "for my family", "timeline": "four or five years"},
    )
    guidance = reasoning.parse_guidance(_response(payload))
    assert guidance.conversation_stage == "objection"
    assert guidance.response_strategy == "handle_objection"
    assert guidance.next_action == "ask"
    assert guidance.fact_ids == ["price", "privacy"]
    assert guidance.lead_evidence["use_case"] == "for my family"
    assert len(guidance.decision_summary.split()) <= 14


def test_parse_guidance_supports_multiple_allowlisted_tool_requests():
    payload = dict(
        GOOD,
        next_action="tool",
        tool_requests=[
            {"name": "send_brochure", "arguments": {"channel": "WhatsApp"}},
            {"name": "schedule_callback", "arguments": {"preferred_time": "tomorrow"}},
            {"name": "invent_discount", "arguments": {}},
        ],
    )
    guidance = reasoning.parse_guidance(_response(payload))
    assert [action.name for action in guidance.tool_requests] == [
        "send_brochure",
        "schedule_callback",
    ]
    assert guidance.tool_request == guidance.tool_requests[0]


def test_wait_strategy_may_return_no_spoken_pitch():
    guidance = reasoning.parse_guidance(_response(dict(GOOD, talking_point="", response_strategy="wait")))
    assert guidance.talking_point == ""


def test_failure_path_is_graceful(monkeypatch):
    """A dead API must produce a ReasoningFailure on the queue — never an exception
    that could reach the audio loop."""
    layer = reasoning.ReasoningLayer(api_key="test-key")

    def boom(self, prompt):
        raise TimeoutError("simulated 6s timeout")

    monkeypatch.setattr(reasoning.ReasoningLayer, "_post", boom)
    layer._call([], "hello?")
    result = layer.results.get_nowait()
    assert isinstance(result, reasoning.ReasoningFailure)
    assert "simulated" in result.reason
    assert layer.stats.failures == 1


def test_quota_exhaustion_never_calls_provider_or_waits(monkeypatch):
    quota = ProviderQuota(requests_per_minute=1, requests_per_day=1)
    with quota.slot():
        pass
    layer = reasoning.ReasoningLayer(api_key="test-key", quota=quota)
    monkeypatch.setattr(layer, "_post", lambda _prompt: pytest.fail("provider must not be called"))

    started = time.perf_counter()
    layer._call([], "tell me about privacy")
    elapsed = time.perf_counter() - started

    result = layer.results.get_nowait()
    assert isinstance(result, reasoning.ReasoningFailure)
    assert "quota exhausted" in result.reason
    assert elapsed < 0.1


def test_cost_accounting():
    stats = reasoning.UsageStats(tokens_in=1_000_000, tokens_out=1_000_000)
    assert stats.cost_usd("gemini-3.1-flash-lite") == pytest.approx(0.50)
    assert stats.cost_usd("unknown-model") == 0.0


def test_missing_key_fails_fast(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        reasoning.ReasoningLayer()


def test_custom_profile_reuses_transport_without_sdr_schema(monkeypatch):
    seen = {}

    def builder(history, utterance):
        seen["builder"] = (history, utterance)
        return "custom prompt"

    def parser(response):
        seen["response"] = response
        return reasoning.Guidance("other", None, "profile result", {})

    layer = reasoning.ReasoningLayer(
        api_key="test-key",
        system_prompt="custom system",
        prompt_builder=builder,
        response_parser=parser,
    )
    monkeypatch.setattr(layer, "_post", lambda prompt: {"prompt": prompt})

    layer._call([("lead", "history")], "answer")

    result = layer.results.get_nowait()
    assert result.talking_point == "profile result"
    assert seen["builder"] == ([("lead", "history")], "answer")
    assert seen["response"] == {"prompt": "custom prompt"}


def test_partial_json_parser_releases_only_a_complete_spoken_field():
    partial = '{"intent":"question","talking_point":"Private foyers improve'
    assert reasoning.extract_complete_json_string(partial, "talking_point") is None
    complete = partial + ' family privacy.\\nWould that matter to you?","fact_ids":["privacy"]}'
    assert reasoning.extract_complete_json_string(complete, "talking_point") == (
        "Private foyers improve family privacy.\nWould that matter to you?"
    )
