import json

from duet_agent.actions import ActionLayer, ActionRequest, parse_action_request, parse_action_requests


def test_action_parser_allowlists_names_and_arguments():
    action = parse_action_request(
        {
            "name": "book_site_visit",
            "arguments": {
                "preferred_time": "Saturday morning",
                "project": "ASBL Broadway",
                "email": "must-not-cross-boundary@example.com",
            },
        }
    )
    assert action == ActionRequest(
        "book_site_visit",
        {"preferred_time": "Saturday morning", "project": "ASBL Broadway"},
    )
    assert parse_action_request({"name": "wire_money"}) is None


def test_multiple_action_parser_is_bounded_and_deduplicated():
    actions = parse_action_requests(
        [
            {"name": "send_brochure", "arguments": {}},
            {"name": "send_brochure", "arguments": {"channel": "WhatsApp"}},
            {"name": "schedule_callback", "arguments": {"preferred_time": "tomorrow"}},
            {"name": "book_site_visit", "arguments": {}},
        ]
    )
    assert [action.name for action in actions] == ["send_brochure", "schedule_callback"]


def test_local_action_is_really_recorded_and_only_claims_acceptance(tmp_path):
    ledger = tmp_path / "actions.jsonl"
    layer = ActionLayer("session-1", mode="local", ledger_path=ledger)

    action_id = layer.request(ActionRequest("schedule_callback", {"preferred_time": "tomorrow"}))
    result = layer.results.get(timeout=1)

    assert result.status == "accepted"
    assert result.reference_id == action_id
    assert result.adapter == "local-demo-ledger"
    assert "recorded" in result.spoken_confirmation.lower()
    assert "scheduled" not in result.spoken_confirmation.lower()
    row = json.loads(ledger.read_text().strip())
    assert row["action_id"] == action_id
    assert row["status"] == "accepted"
    assert row["arguments"]["preferred_time"] == "tomorrow"


def test_disabled_action_never_claims_completion(tmp_path):
    layer = ActionLayer("session-2", mode="disabled", ledger_path=tmp_path / "unused.jsonl")
    layer.request(ActionRequest("send_brochure"))
    result = layer.poll()
    assert result.status == "unavailable"
    assert "not connected" in result.spoken_confirmation

