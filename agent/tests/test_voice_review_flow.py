import datetime as dt
import queue
import sys
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace

WEB_DEMO = Path(__file__).resolve().parents[2] / "web-demo"
sys.path.insert(0, str(WEB_DEMO))

from server import Session  # noqa: E402

from duet_agent.actions import ActionRequest, ActionResult  # noqa: E402
from duet_agent.hermes import RecallDeck, TutorSession  # noqa: E402
from duet_agent.reasoning import Guidance, SpeechPreview  # noqa: E402


def _session():
    deck = RecallDeck(
        root=Path("/tmp/hermes-test"),
        slug="test",
        title="Test",
        due_at=dt.date(2026, 8, 2),
        questions=("Question one?", "Question two?"),
        study_material="",
    )
    session = Session.__new__(Session)
    session.args = SimpleNamespace(hermes_remote_grading=False, voice_stack="open", mode="hermes")
    session.tutor = TutorSession(deck)
    session.capture = None
    spoken = []
    events = []
    session.speak = spoken.append
    session.emit = lambda **event: events.append(event)
    return session, spoken, events


def test_explicit_give_up_advances_without_silent_grade_gate():
    session, spoken, _events = _session()

    session._accept_transcript("I don't know the answer.", 200, [], None)

    assert session.tutor.index == 1
    assert session.tutor.pending_answer is None
    assert "Next question: Question two?" in spoken[-1]


def test_normal_answer_prompts_for_and_accepts_spoken_self_grade():
    session, spoken, events = _session()
    history = []

    session._accept_transcript("The server is the resource server.", 200, history, None)

    assert session.tutor.pending_answer is not None
    assert "How would you grade it" in spoken[-1]
    assert any(event["type"] == "tutor_answer" for event in events)

    session._accept_transcript("That was correct.", 180, history, None)

    assert session.tutor.index == 1
    assert session.tutor.pending_answer is None
    assert "Next question: Question two?" in spoken[-1]


def test_barge_in_cancels_current_and_buffered_speech():
    session = Session.__new__(Session)
    session.args = SimpleNamespace(barge_in=True)
    session.agent_speaking = threading.Event()
    session.agent_speaking.set()
    session.cancel_speech = threading.Event()
    session.spk_q = queue.Queue()
    session.speech_q = queue.Queue()
    session.spk_q.put(object())
    session.speech_q.put("stale reply")
    events = []
    session.emit = lambda **event: events.append(event)

    session.interrupt_playback("actually, wait")

    assert session.cancel_speech.is_set()
    assert session.spk_q.empty()
    assert session.speech_q.empty()
    assert events[0]["type"] == "playback_cancel"


def _sdr_session():
    session = Session.__new__(Session)
    session.args = SimpleNamespace(mode="sdr", barge_in=False)
    session.tutor = None
    session.capture = None
    session.sdr_permission = "pending"
    session.sdr_opted_out = False
    session.sdr_clarification_pending = False
    session.barge_in_pending = False
    session.latest_brain_request_id = 0
    session.speculative_request_id = 0
    session.speculative_text = ""
    session.speculative_committed_ids = set()
    session.speculative_results = {}
    session.ready_brain_results = deque()
    session.pending_speech_previews = {}
    session.early_spoken_ids = set()
    session.recent_agent_responses = deque(maxlen=4)
    spoken = []
    events = []
    session.speak = spoken.append
    session.emit = lambda **event: events.append(event)
    session.interrupt_playback = lambda _text="": None
    return session, spoken, events


def test_sdr_requires_permission_before_discovery():
    session, spoken, events = _sdr_session()
    history = []

    session._accept_transcript("Yes, this is a good time.", 120, history, None)

    assert session.sdr_permission == "granted"
    assert "home for your family" in spoken[-1]
    assert any(event.get("state") == "permission_granted" for event in events)


def test_sdr_opt_out_is_fail_closed_and_disables_reasoning():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"

    session._accept_transcript("Please stop calling and remove me.", 90, [], None)

    assert session.sdr_opted_out
    assert "stop here" in spoken[-1]
    assert any(event.get("state") == "do_not_contact" for event in events)


def test_trial_wording_latches_opt_out_and_blocks_later_action_reasoning():
    session, spoken, _events = _sdr_session()
    session.sdr_permission = "granted"

    class Brain:
        called = False

        def request(self, *_args):
            self.called = True

    brain = Brain()
    history = []
    session._accept_transcript("I don't want to listen about that.", 90, history, brain)
    session._accept_transcript("Schedule a site visit and send the brochure.", 90, history, brain)

    assert session.sdr_opted_out
    assert len(spoken) == 1
    assert not brain.called


def test_ambiguous_barge_in_clarifies_without_calling_reasoning():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"
    session.barge_in_pending = True

    class Brain:
        called = False

        def request(self, *_args):
            self.called = True

    brain = Brain()
    session._accept_transcript("I just changed my mind, yeah yeah.", 80, [], brain)

    assert session.sdr_clarification_pending
    assert "want me to stop" in spoken[-1]
    assert not brain.called
    assert any(event.get("state") == "clarification_required" for event in events)


def test_pause_barge_in_is_acknowledged_without_calling_reasoning():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"
    session.barge_in_pending = True

    class Brain:
        called = False

        def request(self, *_args):
            self.called = True

    brain = Brain()
    session._accept_transcript("Uh, wait a minute.", 80, [], brain)

    assert "Take your time" in spoken[-1]
    assert not session.barge_in_pending
    assert not brain.called
    assert any(event.get("state") == "interruption_acknowledged" for event in events)


def test_vague_barge_in_asks_what_caller_meant():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"
    session.barge_in_pending = True

    class Brain:
        called = False

        def request(self, *_args):
            self.called = True

    brain = Brain()
    session._accept_transcript("Actually, no.", 80, [], brain)

    assert "trying to ask" in spoken[-1]
    assert session.sdr_clarification_pending
    assert not brain.called
    assert any(event.get("state") == "clarification_required" for event in events)


def test_presence_check_after_barge_in_gets_a_human_acknowledgment():
    session, spoken, _events = _sdr_session()
    session.sdr_permission = "granted"
    session.barge_in_pending = True

    session._accept_transcript("Are you talking?", 80, [], None)

    assert "I'm here" in spoken[-1]
    assert "listening" in spoken[-1]


def test_speech_start_yields_before_transcript_and_marks_pending_interruption():
    session = Session.__new__(Session)
    session.args = SimpleNamespace(barge_in=True)
    session.agent_speaking = threading.Event()
    session.agent_speaking.set()
    interrupted = []
    session.interrupt_playback = interrupted.append
    session.barge_in_pending = False

    session.handle_speech_start()

    assert session.barge_in_pending
    assert interrupted == [""]


def test_stable_partial_reasoning_is_held_then_committed_by_matching_final():
    session, _spoken, events = _sdr_session()
    session.sdr_permission = "granted"

    class Brain:
        def __init__(self):
            self.calls = []

        def request(self, history, text):
            self.calls.append((list(history), text))
            return len(self.calls)

    brain = Brain()
    history = []
    partial = "I need a family home near Financial District"
    session._start_speculative_reasoning(partial, history, brain)
    session._accept_transcript(
        "I need a family home near Financial District with three bedrooms",
        45,
        history,
        brain,
    )

    assert len(brain.calls) == 1
    assert session.latest_brain_request_id == 1
    assert 1 in session.speculative_committed_ids
    assert any(event.get("state") == "speculation_committed" for event in events)


def test_changed_final_replaces_speculative_reasoning():
    session, _spoken, events = _sdr_session()
    session.sdr_permission = "granted"

    class Brain:
        def __init__(self):
            self.calls = []

        def request(self, history, text):
            self.calls.append((list(history), text))
            return len(self.calls)

    brain = Brain()
    session._start_speculative_reasoning("I need a family home near Financial District", [], brain)
    session._accept_transcript("Actually this is only an investment purchase", 45, [], brain)

    assert len(brain.calls) == 2
    assert session.latest_brain_request_id == 2
    assert any(event.get("state") == "speculation_replaced" for event in events)


def test_streamed_spoken_field_reaches_mouth_before_final_metadata():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"
    session.latest_brain_request_id = 4

    class Brain:
        preview = SpeechPreview(4, "Why does privacy matter?", "Private foyers keep arrivals discreet.", 310)

        def poll_preview(self):
            result, self.preview = self.preview, None
            return result

    history = []
    session._poll_brain_preview(Brain(), history)

    assert spoken == ["Private foyers keep arrivals discreet."]
    assert history[-1][0] == "agent"
    assert 4 in session.early_spoken_ids
    assert any(event.get("state") == "early_speech" for event in events)


def test_transactional_stream_preview_waits_for_tool_result():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"
    session.latest_brain_request_id = 5

    class Brain:
        preview = SpeechPreview(5, "Schedule a site visit", "I am putting that through now.", 280)

        def poll_preview(self):
            result, self.preview = self.preview, None
            return result

    session._poll_brain_preview(Brain(), [])

    assert not spoken
    assert 5 not in session.early_spoken_ids
    assert any(event.get("state") == "early_speech_gated" for event in events)


def test_sdr_backchannel_waits_without_calling_reasoning():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"

    class Brain:
        called = False

        def request(self, *_args):
            self.called = True

    brain = Brain()
    session._accept_transcript("Hmm", 80, [], brain)

    assert not spoken
    assert not brain.called
    assert any(event.get("state") == "listener_backchannel" for event in events)


def test_transactional_turn_speaks_real_action_receipts_not_planner_promise():
    session, spoken, events = _sdr_session()
    session.sdr_permission = "granted"

    class Actions:
        enabled = True
        capability_label = "local demo ledger"

        def __init__(self):
            self.requested = []
            self.results = queue.Queue()

        def request(self, action):
            self.requested.append(action)
            action_id = f"action-{len(self.requested)}"
            self.results.put(
                ActionResult(
                    action.name,
                    "accepted",
                    reference_id=action_id,
                    adapter="local-demo-ledger",
                )
            )
            return action_id

        def poll(self):
            try:
                return self.results.get_nowait()
            except queue.Empty:
                return None

    class Brain:
        def __init__(self, result):
            self.result = result

        def poll(self):
            result, self.result = self.result, None
            return result

    session.action_layer = Actions()
    guidance = Guidance(
        intent="callback",
        objection_type=None,
        talking_point="I have sent the brochure and scheduled the callback.",
        lead_signals={dimension: "none" for dimension in ("budget_fit", "decision_role", "use_case", "timeline")},
        next_action="tool",
        tool_requests=[
            ActionRequest("send_brochure"),
            ActionRequest("schedule_callback", {"preferred_time": "tomorrow"}),
        ],
    )

    session._poll_brain(Brain(guidance), [])

    assert spoken == []
    assert [action.name for action in session.action_layer.requested] == [
        "send_brochure",
        "schedule_callback",
    ]
    assert len([event for event in events if event["type"] == "action"]) == 2

    session._poll_actions([])
    session._poll_actions([])
    assert all("recorded" in line.lower() for line in spoken)
    assert all("done" not in line.lower() for line in spoken)
