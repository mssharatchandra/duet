from duet_agent import persona


def test_score_lead_full_readiness():
    signals = {dimension: "strong" for dimension in persona.QUALIFICATION_DIMENSIONS}
    score = persona.score_lead(signals)
    assert score.total == 100
    assert score.verdict == "site_visit_ready"


def test_score_lead_partial_and_unknown_labels():
    signals = {"budget_fit": "weak", "decision_role": "banana", "use_case": "strong"}
    score = persona.score_lead(signals)
    assert score.breakdown == {
        "budget_fit": 12,
        "decision_role": 0,
        "use_case": 25,
        "timeline": 0,
    }
    assert score.total == 37
    assert score.verdict == "nurture_or_disqualify"


def test_score_lead_follow_up_band():
    score = persona.score_lead(
        {"budget_fit": "weak", "decision_role": "weak", "use_case": "strong", "timeline": "none"}
    )
    assert score.verdict == "advisor_follow_up"


def test_build_prompt_bounds_and_deduplicates_current_turn():
    history = [("lead", f"line {i}") for i in range(50)]
    prompt = persona.build_prompt(history, "line 49")
    assert "line 49" in prompt and "line 0" not in prompt
    assert prompt.count("lead: line 49") == 1
    assert prompt.rstrip().endswith("Return the JSON now.")


def test_playbook_covers_real_estate_objections():
    expected = {"price", "timing", "location", "trust", "comparison", "family_approval", "investment_returns"}
    assert expected <= set(persona.OBJECTION_PLAYBOOK)


def test_system_prompt_is_grounded_and_forbids_manipulative_profiling():
    assert "ASBL Broadway" in persona.SYSTEM_PROMPT
    assert "December 2029" in persona.SYSTEM_PROMPT
    assert "INR 3 crore" in persona.SYSTEM_PROMPT
    assert "Do not infer personality" in persona.SYSTEM_PROMPT
    assert "Never claim to be human" in persona.SYSTEM_PROMPT


def test_permission_and_opt_out_policy_is_deterministic():
    assert persona.permission_response("Yes, this is a good time") == "granted"
    assert persona.permission_response("I'm busy, call later") == "denied"
    assert persona.permission_response("Who is this?") is None
    assert persona.is_opt_out("Please remove me from the list")
    assert persona.is_opt_out("I am not interested")
    assert not persona.is_opt_out("I am interested in a larger home")


def test_trial_backchannels_do_not_trigger_a_sales_turn():
    assert persona.is_backchannel("Hmm.")
    assert persona.is_backchannel("Okay")
    assert not persona.is_backchannel("Yes, a family home")
    assert not persona.is_backchannel("Actually, four or five years")


def test_barge_in_ignores_acknowledgements_and_likely_echo():
    spoken = "Broadway offers private foyers and spacious three bedroom homes."
    assert not persona.should_interrupt("hmm", spoken)
    assert not persona.should_interrupt("private foyers and spacious three bedroom homes", spoken)
    assert persona.should_interrupt("actually, wait", spoken)
    assert persona.should_interrupt("tell me about price", spoken)


def test_trial_opt_out_language_and_ambiguous_change_are_distinct():
    assert persona.is_opt_out("I don't want to listen about that.")
    assert persona.is_opt_out("Please end the call")
    assert not persona.is_opt_out("I just changed my mind, yeah yeah")
    assert persona.is_ambiguous_change("I just changed my mind, yeah yeah")
    assert persona.clarification_response("No, stop the conversation") == "stop"
    assert persona.clarification_response("Keep going, I want to change my preference") == "continue"


def test_explicit_change_and_question_are_not_misclassified_as_vague():
    preference = "I just changed my mind, I want to buy it for my family."
    question = "Can you tell me about the price?"

    assert persona.has_usable_interruption_intent(preference)
    assert not persona.is_ambiguous_change(preference)
    assert not persona.needs_interruption_clarification(preference)
    assert persona.clarification_response(preference) == "resolved"
    assert persona.clarification_response(question) == "resolved"


def test_interruption_semantics_distinguish_pause_presence_and_vague_change():
    assert persona.is_pause_request("Wait a minute, please")
    assert persona.is_pause_request("Hold on")
    assert persona.is_presence_check("Are you talking?")
    assert persona.needs_interruption_clarification("Actually, no")
    assert not persona.needs_interruption_clarification("Wait a minute")
    assert not persona.needs_interruption_clarification("Tell me about the current price")


def test_stable_partial_must_preserve_final_meaning():
    assert persona.partial_matches_final(
        "I want a family home near Financial District",
        "I want a family home near Financial District with three bedrooms",
    )
    assert not persona.partial_matches_final(
        "I want a family home",
        "I do not want a family home; this is an investment",
    )


def test_short_stable_partial_can_now_speculate_down_to_the_shared_floor():
    # docs/DECISIONS.md 0029: lowered from 4 to MIN_SPECULATIVE_WORDS(=2) words so
    # short high-frequency turns (a two-word question, a quick yes/no answer) are
    # eligible for latency-masking speculation instead of always paying full
    # Gemini latency on the critical path.
    assert persona.partial_matches_final("what price", "what price please")
    # Below the shared floor, still never eligible -- one word is too thin to
    # safely commit reasoning to before the speaker has finished a thought.
    assert not persona.partial_matches_final("what", "what price please")


def test_transactional_requests_do_not_use_early_streamed_speech():
    assert persona.is_transactional_request("Send me the brochure on WhatsApp")
    assert persona.is_transactional_request("Please schedule a site visit")
    assert not persona.is_transactional_request("Why is Broadway useful for a family?")


def test_capability_gate_blocks_fake_crm_actions():
    assert persona.response_problem("I'll send the brochure and arrange an advisor.") == "unavailable_tool_claim"
    assert persona.response_problem("I have updated your status.") == "unavailable_tool_claim"
    assert persona.response_problem("An advisor will contact you tomorrow.") == "unavailable_tool_claim"
    assert persona.response_problem("The public starting price is around three crore.") is None


def test_sensitive_trait_profiling_is_detected_without_blocking_normal_preferences():
    assert persona.is_sensitive_profiling_request("Use my religion to judge whether I am likely to buy")
    assert persona.is_sensitive_profiling_request("I'm Muslim. Does that make me likely to buy?")
    assert not persona.is_sensitive_profiling_request("I need a home near my workplace for my family")


def test_repetition_detector_catches_trial_failure():
    previous = ["Broadway stands out because private foyers protect family privacy."]
    repeated = "Broadway stands out because its private foyers protect your family's privacy."
    assert persona.is_repetitive_response(repeated, previous)


def test_fact_registry_resolves_only_allowlisted_sources():
    facts = persona.resolve_fact_ids(["privacy", "made_up", "price"])
    assert [fact["id"] for fact in facts] == ["privacy", "price"]
    assert all(fact["source_url"].startswith("https://asbl.in/") for fact in facts)


def test_domain_normalization_fixes_trial_asr_error_conservatively():
    assert persona.normalize_domain_terms("Why should I buy ASP Broadway?") == "Why should I buy ASBL Broadway?"
    assert persona.normalize_domain_terms("Show me the broad way plan") == "Show me the Broadway plan"
