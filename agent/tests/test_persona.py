from duet_agent import persona


def test_score_lead_full_bant():
    s = persona.score_lead({"budget": "strong", "authority": "strong", "need": "strong", "timeline": "strong"})
    assert s.total == 100
    assert s.verdict == "qualified"


def test_score_lead_partial_and_unknown_labels():
    s = persona.score_lead({"budget": "weak", "authority": "banana", "need": "strong"})  # timeline missing
    assert s.breakdown == {"budget": 12, "authority": 0, "need": 25, "timeline": 0}
    assert s.total == 37
    assert s.verdict == "not a fit"


def test_score_lead_nurture_band():
    s = persona.score_lead({"budget": "weak", "authority": "weak", "need": "strong", "timeline": "none"})
    assert s.verdict == "nurture"


def test_build_prompt_bounds_history():
    history = [("lead", f"line {i}") for i in range(50)]
    prompt = persona.build_prompt(history, "final question")
    assert "line 49" in prompt and "line 0" not in prompt  # cost control: context is bounded
    assert prompt.rstrip().endswith("Respond with the JSON now.")
    assert "final question" in prompt


def test_playbook_covers_briefs_three_objections():
    assert set(persona.OBJECTION_PLAYBOOK) == {"status_quo", "price", "no_time"}


def test_system_prompt_grounded_in_fact_sheet():
    assert "$99/mo" in persona.SYSTEM_PROMPT and "Brewline" in persona.SYSTEM_PROMPT
