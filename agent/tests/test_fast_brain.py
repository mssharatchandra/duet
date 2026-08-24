"""Pure tests for the fast steering brain's text handling.

Deliberately no MLX: `clean_phrase` is the part that decides what actually
reaches the duplex model's token stream, and it must stay verifiable on the
stdlib-only CI tier alongside the rest of the brain-side modules.
"""

from duet_agent.fast_brain import clean_phrase


def test_stops_at_turn_boundary_instead_of_speaking_model_debris():
    # Gemma emits <end_of_turn> and then keeps talking to itself; measured
    # output included repeated end-of-turn markers and stray non-Latin tokens.
    raw = "Around three crore.<end_of_turn>چல.<end_of_turn> précision.<end_of_turn>"
    assert clean_phrase(raw) == "Around three crore."


def test_strips_typographic_quotes_that_would_be_spoken_or_tokenized_as_debris():
    assert clean_phrase("“Okay, let’s talk about a price range.”") == "Okay, let’s talk about a price range."
    assert clean_phrase('"Yes, this weekend works."') == "Yes, this weekend works."


def test_keeps_only_the_first_line():
    assert clean_phrase("First reply here.\nThen it rambles on.") == "First reply here."


def test_collapses_whitespace_so_pacing_is_predictable():
    assert clean_phrase("  Around   three\tcrore.  ") == "Around three crore."


def test_empty_and_marker_only_output_yields_nothing_speakable():
    assert clean_phrase("") == ""
    assert clean_phrase("<end_of_turn>") == ""
    assert clean_phrase('  "" ') == ""
