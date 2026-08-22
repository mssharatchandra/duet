import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from duet_agent.hermes import (
    HermesError,
    TutorGuidance,
    TutorSession,
    is_explicit_give_up,
    load_recall_deck,
    parse_recall_questions,
    parse_spoken_grade,
    parse_tutor_guidance,
    record_review,
)


def _make_brain(root: Path, *, slug="approved-run", status="approved", due_at=None) -> Path:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "brain.py").write_text("# test fixture\n")
    run = root / "learning" / slug
    run.mkdir(parents=True)
    manifest = {
        "slug": slug,
        "title": "A reviewed topic",
        "status": status,
        "artifacts": {"recall": "recall.md", "article": "article.mdx", "events": "events.jsonl"},
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "recall.md").write_text(
        "# Recall\n\n## Questions\n\n1. What is one?\n"
        "2. Explain two, including\n   the important boundary.\n\n## Review log\n"
    )
    (run / "article.mdx").write_text("Reviewed facts live here.")
    events = [{"kind": "run.created", "data": {}}]
    if due_at:
        events.append({"kind": "review.completed", "data": {"due_at": due_at}})
    (run / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    return run


def _response(verdict="correct", feedback="That captures the key boundary."):
    return {
        "candidates": [{"content": {"parts": [{"text": json.dumps({
            "verdict": verdict,
            "feedback": feedback,
            "answer_summary": "A short answer",
        })}]}}],
        "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 8},
    }


def test_parse_recall_questions_handles_wrapping_and_stops_at_review_log():
    document = "# Recall\n## Questions\n1. First?\n2. A wrapped\n   question?\n## Review log\n1. not a question"
    assert parse_recall_questions(document) == ["First?", "A wrapped question?"]


def test_loads_oldest_due_approved_run(tmp_path):
    _make_brain(tmp_path, slug="later", due_at="2026-08-01")
    _make_brain(tmp_path, slug="earlier", due_at="2026-07-20")
    _make_brain(tmp_path, slug="draft", status="researching")

    deck = load_recall_deck(tmp_path, today=dt.date(2026, 8, 1))

    assert deck.slug == "earlier"
    assert deck.questions == ("What is one?", "Explain two, including the important boundary.")
    assert deck.study_material == "Reviewed facts live here."


def test_default_rejects_when_nothing_is_due_but_explicit_slug_can_practice(tmp_path):
    _make_brain(tmp_path, due_at="2026-08-10")
    today = dt.date(2026, 8, 1)
    with pytest.raises(HermesError, match="no approved Hermes reviews are due"):
        load_recall_deck(tmp_path, today=today)
    assert load_recall_deck(tmp_path, slug="approved-run", today=today).slug == "approved-run"


def test_tutor_repeat_does_not_advance_and_strict_score_counts_only_correct(tmp_path):
    _make_brain(tmp_path)
    tutor = TutorSession(load_recall_deck(tmp_path, today=dt.date(2026, 8, 1)))

    assert tutor.accept_answer("Could you repeat that?")
    assert "What is one?" in tutor.apply_grade(TutorGuidance("repeat", "Repeating."))
    assert tutor.index == 0 and tutor.attempted == 0

    assert tutor.accept_answer("My first answer")
    assert "Next question" in tutor.apply_grade(TutorGuidance("partial", "You missed the boundary."))
    assert tutor.accept_answer("My second answer")
    assert "Review complete" in tutor.apply_grade(TutorGuidance("correct", "Exactly."))
    assert tutor.complete and tutor.strict_correct == 1 and tutor.attempted == 2


def test_parse_tutor_guidance_validates_schema():
    result = parse_tutor_guidance(_response())
    assert result.verdict == "correct" and result.tokens_in == 20 and result.tokens_out == 8
    with pytest.raises(ValueError, match="invalid verdict"):
        parse_tutor_guidance(_response(verdict="close-enough"))


@pytest.mark.parametrize(
    ("spoken", "verdict"),
    [
        ("Correct", "correct"),
        ("That was correct.", "correct"),
        ("It was only partially right", "partial"),
        ("No, that was wrong", "incorrect"),
        ("Skip", "skip"),
        ("Please repeat the question", "repeat"),
        ("The correct role is resource server", None),
    ],
)
def test_parse_spoken_grade_is_conservative(spoken, verdict):
    assert parse_spoken_grade(spoken) == verdict


def test_explicit_give_up_is_detected_but_not_inside_a_long_answer():
    assert is_explicit_give_up("Uh, I think. I don't know, I don't know the answer.")
    assert is_explicit_give_up("I have no idea")
    assert not is_explicit_give_up(
        "The client does not know the verifier, but I don't know whether that changes the authorization role "
        "because the server still validates the challenge."
    )


def test_record_review_uses_hermes_cli_and_verifies_appended_event(tmp_path):
    run = _make_brain(tmp_path)
    tutor = TutorSession(load_recall_deck(tmp_path, today=dt.date(2026, 8, 1)))
    for verdict in ("correct", "incorrect"):
        assert tutor.accept_answer("answer")
        tutor.apply_grade(TutorGuidance(verdict, f"Marked {verdict}."))

    seen = {}

    def fake_runner(command, **kwargs):
        seen["command"] = command
        seen["cwd"] = kwargs["cwd"]
        data = {"correct": 1, "total": 2, "score": 0.5, "interval_days": 1, "due_at": "2026-08-02", "notes": ""}
        with (run / "events.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "review.completed", "data": data}) + "\n")
        return subprocess.CompletedProcess(command, 0, json.dumps(data), "")

    data = record_review(tutor, runner=fake_runner)

    assert seen["cwd"] == tmp_path
    assert seen["command"][:4] == ["python3", "scripts/brain.py", "review", "approved-run"]
    assert data["correct"] == 1 and tutor.recorded
    with pytest.raises(HermesError, match="already recorded"):
        record_review(tutor, runner=fake_runner)
