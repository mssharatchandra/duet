from duet_agent.turns import TurnAssembler


def test_commits_one_segment_after_grace():
    turns = TurnAssembler(continuation_grace_s=0.4)
    turns.speech_started()
    turns.speech_ended(1.0)
    turns.add_transcript("hello there", 1.1)
    assert turns.poll(1.49) is None
    assert turns.poll(1.5) == "hello there"


def test_resume_during_grace_merges_acoustic_segments():
    turns = TurnAssembler(continuation_grace_s=0.4)
    turns.speech_started()
    turns.speech_ended(1.0)
    turns.add_transcript("I haven't read that part of the", 1.1)
    turns.speech_started()  # same ordering observed from Sarvam: data, then START_SPEECH
    assert turns.poll(2.0) is None
    turns.speech_ended(2.2)
    turns.add_transcript("uh, what the blog", 2.3)
    assert turns.poll(2.69) is None
    assert turns.poll(2.7) == "I haven't read that part of the, uh, what the blog"


def test_cumulative_provider_revision_does_not_duplicate_text():
    turns = TurnAssembler(continuation_grace_s=0)
    turns.add_transcript("hello", 1.0)
    turns.add_transcript("hello world", 1.1)
    assert turns.poll(1.1) == "hello world"


def test_reset_drops_incomplete_turn():
    turns = TurnAssembler()
    turns.add_transcript("stale", 1.0)
    turns.reset()
    assert turns.poll(10.0) is None


def test_unfinished_language_gets_longer_thinking_pause():
    turns = TurnAssembler(continuation_grace_s=0.4, hesitation_grace_s=1.1)
    turns.add_transcript("The MCP client acts as the", 1.0)
    assert turns.poll(1.5) is None
    assert turns.poll(2.1) == "The MCP client acts as the"


def test_complete_sentence_keeps_fast_endpoint():
    turns = TurnAssembler(continuation_grace_s=0.4, hesitation_grace_s=1.1)
    turns.add_transcript("The MCP server is the resource server.", 1.0)
    assert turns.poll(1.39) is None
    assert turns.poll(1.4) == "The MCP server is the resource server."


def test_reformulation_marker_gets_long_grace_from_trial_transcript():
    turns = TurnAssembler(continuation_grace_s=0.4, discourse_grace_s=2.1)
    turns.add_transcript("Actually", 1.0)
    assert turns.poll(2.9) is None
    turns.speech_started()
    turns.speech_ended(3.0)
    turns.add_transcript("I am looking at four or five years", 3.1)
    assert turns.poll(3.49) is None
    assert turns.poll(3.5) == "Actually I am looking at four or five years"
