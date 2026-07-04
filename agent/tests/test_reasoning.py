import json

import pytest

from duet_agent import reasoning


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
    "talking_point": "It's ninety-nine a month and the trial is free.",
    "lead_signals": {"budget": "weak", "authority": "strong", "need": "strong", "timeline": "none"},
}


def test_parse_guidance_happy_path():
    g = reasoning.parse_guidance(_response(GOOD))
    assert g.intent == "objection"
    assert g.objection_type == "price"
    assert g.tokens_in == 100 and g.tokens_out == 40


def test_parse_guidance_strips_markdown_fences():
    g = reasoning.parse_guidance(_response(GOOD, fenced=True))
    assert g.talking_point.startswith("It's ninety-nine")


def test_parse_guidance_coerces_invalid_enums():
    bad = dict(GOOD, intent="sales_magic", objection_type="vibes", lead_signals={"budget": "HUGE"})
    g = reasoning.parse_guidance(_response(bad))
    assert g.intent == "other"
    assert g.objection_type is None
    assert g.lead_signals == {"budget": "none", "authority": "none", "need": "none", "timeline": "none"}


def test_parse_guidance_rejects_empty_talking_point():
    with pytest.raises(Exception):
        reasoning.parse_guidance(_response(dict(GOOD, talking_point="  ")))


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


def test_cost_accounting():
    stats = reasoning.UsageStats(tokens_in=1_000_000, tokens_out=1_000_000)
    assert stats.cost_usd("gemini-3.1-flash-lite") == pytest.approx(0.50)
    assert stats.cost_usd("unknown-model") == 0.0


def test_missing_key_fails_fast(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        reasoning.ReasoningLayer()
