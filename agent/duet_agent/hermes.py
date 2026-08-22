"""Pure Hermes Brain adapter for Duet's spoken-recall mode.

The durable learning state remains owned by ``hermes-brain``.  Duet reads its
approved recall artifacts, runs one voice review, and delegates the final write
back to Hermes' own ``brain.py review`` command.  Keeping that boundary narrow
means a voice UI cannot quietly invent a second scheduling implementation.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REVIEWABLE_STATUSES = {"approved", "published"}
VERDICTS = {"correct", "partial", "incorrect", "repeat", "skip"}


class HermesError(RuntimeError):
    """A user-fixable Hermes integration error."""


def parse_spoken_grade(text: str) -> str | None:
    """Parse an explicit local self-grade without asking an LLM.

    Keep this deliberately conservative: normal answer text must not be
    mistaken for a control command merely because it contains a word such as
    "correct".  This is called only while an answer is already pending.
    """
    phrase = re.sub(r"[^a-z0-9' ]+", " ", text.casefold().replace("’", "'"))
    phrase = " ".join(phrase.split())
    if re.search(r"\b(repeat( the question)?|say (it|that) again)\b", phrase):
        return "repeat"
    if re.search(r"\b(partial|partially|partly)\b", phrase):
        return "partial"
    if re.search(r"\b(incorrect|wrong|not correct)\b", phrase):
        return "incorrect"
    if re.fullmatch(r"(yes[, ]*)?(correct|right|i got it right|that was correct)", phrase):
        return "correct"
    if re.fullmatch(r"(skip|pass|i (don't|do not) know( the answer)?|i have no idea|no idea)", phrase):
        return "skip"
    return None


def is_explicit_give_up(text: str) -> bool:
    """Recognize a short answer that explicitly gives up on the question."""
    phrase = re.sub(r"[^a-z0-9' ]+", " ", text.casefold().replace("’", "'"))
    words = phrase.split()
    if len(words) > 18:
        return False
    return bool(
        re.search(r"\bi (?:don't|do not) know(?: the answer)?\b", phrase)
        or re.search(r"\bi have no idea\b|\bno idea\b", phrase)
        or re.fullmatch(r"\s*(skip|pass)\s*", phrase)
    )


@dataclass(frozen=True)
class RecallDeck:
    root: Path
    slug: str
    title: str
    due_at: dt.date
    questions: tuple[str, ...]
    study_material: str


@dataclass
class TutorGuidance:
    verdict: str
    feedback: str
    answer_summary: str = ""
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class TutorResult:
    question: str
    answer: str
    verdict: str
    feedback: str


@dataclass
class TutorSession:
    """Deterministic review state around a probabilistic (or human) grader."""

    deck: RecallDeck
    index: int = 0
    strict_correct: int = 0
    results: list[TutorResult] = field(default_factory=list)
    pending_answer: str | None = None
    recorded: bool = False

    @property
    def complete(self) -> bool:
        return self.index >= len(self.deck.questions)

    @property
    def attempted(self) -> int:
        return len(self.results)

    @property
    def current_question(self) -> str:
        if self.complete:
            raise HermesError("the review is already complete")
        return self.deck.questions[self.index]

    def opening(self) -> str:
        return f"Let's review {self.deck.title}. Question one: {self.current_question}"

    def accept_answer(self, answer: str) -> bool:
        """Reserve the current question for one answer; reject overlapping ASR turns."""
        if self.complete or self.pending_answer is not None or not answer.strip():
            return False
        self.pending_answer = answer.strip()
        return True

    def grading_prompt(self, _history: list[tuple[str, str]], answer: str) -> str:
        return (
            f"Question {self.index + 1} of {len(self.deck.questions)}:\n{self.current_question}\n\n"
            f"Learner answer:\n{answer}\n\nGrade only this answer and return the required JSON."
        )

    def apply_grade(self, guidance: TutorGuidance) -> str:
        if self.pending_answer is None:
            raise HermesError("no learner answer is waiting to be graded")
        if guidance.verdict not in VERDICTS:
            raise HermesError(f"invalid tutor verdict: {guidance.verdict}")

        if guidance.verdict == "repeat":
            self.pending_answer = None
            return f"Of course. {self.current_question}"

        question = self.current_question
        answer = self.pending_answer
        self.pending_answer = None
        self.results.append(TutorResult(question, answer, guidance.verdict, guidance.feedback))
        if guidance.verdict == "correct":
            self.strict_correct += 1
        self.index += 1

        prefix = guidance.feedback.strip() or f"Marked {guidance.verdict}."
        if self.complete:
            return f"{prefix} Review complete. You got {self.strict_correct} of {self.attempted} strictly correct."
        return f"{prefix} Next question: {self.current_question}"

    def self_grade(self, verdict: str) -> TutorGuidance:
        if verdict not in {"correct", "partial", "incorrect", "skip"}:
            raise HermesError("self-grade must be correct, partial, incorrect, or skip")
        return TutorGuidance(verdict=verdict, feedback=f"Marked {verdict}.")

    def system_prompt(self) -> str:
        # Private Hermes material is included only when the server was started with
        # explicit remote grading consent.  Self-grading never calls this method.
        material = self.deck.study_material[:50_000]
        return f"""\
You grade spoken retrieval practice against the reviewed study material below.
Be strict but useful. Judge the learner's meaning, not exact wording. "correct"
means materially complete; "partial" means the core is present with an important
gap; "incorrect" means the central model is wrong. Use "repeat" only when the
learner explicitly asks to hear the question again, and "skip" only when they
explicitly give up.

Respond ONLY with JSON:
{{
  "verdict": "correct" | "partial" | "incorrect" | "repeat" | "skip",
  "feedback": "one specific spoken sentence, at most 20 words",
  "answer_summary": "a short factual summary of what the learner said"
}}

REVIEWED STUDY MATERIAL
{material}
"""


def default_hermes_root() -> Path:
    # duet/agent/duet_agent/hermes.py -> CURIOUS/hermes-brain
    return Path(__file__).resolve().parents[3] / "hermes-brain"


def load_recall_deck(root: Path | str, slug: str | None = None, today: dt.date | None = None) -> RecallDeck:
    """Load one approved review deck, preferring the oldest due run.

    An explicit slug may select an approved run that is not currently due; the
    default path only selects due work, matching ``brain.py due``.
    """
    root = Path(root).expanduser().resolve()
    learning = root / "learning"
    if not (root / "scripts" / "brain.py").is_file() or not learning.is_dir():
        raise HermesError(f"not a hermes-brain checkout: {root}")
    today = today or dt.datetime.now(dt.UTC).date()

    candidates: list[tuple[dt.date, Path, dict]] = []
    for run_dir in sorted(path for path in learning.iterdir() if path.is_dir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = _read_json(manifest_path)
        if manifest.get("status") not in REVIEWABLE_STATUSES:
            continue
        run_slug = str(manifest.get("slug", ""))
        if slug is not None and run_slug != slug:
            continue
        due_at = _review_due_at(run_dir, manifest, today)
        if slug is not None or due_at <= today:
            candidates.append((due_at, run_dir, manifest))

    if not candidates:
        detail = f"approved run {slug!r} was not found" if slug else "no approved Hermes reviews are due"
        raise HermesError(detail)

    due_at, run_dir, manifest = min(candidates, key=lambda item: (item[0], item[1].name))
    artifacts = manifest.get("artifacts", {})
    recall_path = run_dir / str(artifacts.get("recall", "recall.md"))
    article_path = run_dir / str(artifacts.get("article", "article.mdx"))
    questions = tuple(parse_recall_questions(recall_path.read_text(encoding="utf-8")))
    if not questions:
        raise HermesError(f"no numbered recall questions found in {recall_path}")
    try:
        study_material = article_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HermesError(f"missing reviewed study material: {article_path}") from exc
    return RecallDeck(
        root=root,
        slug=str(manifest["slug"]),
        title=str(manifest["title"]),
        due_at=due_at,
        questions=questions,
        study_material=study_material,
    )


def parse_recall_questions(document: str) -> list[str]:
    """Parse the numbered list under a recall file's Questions section."""
    questions: list[str] = []
    current: list[str] = []
    in_questions = False
    for raw in document.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            if in_questions and "question" not in heading:
                break
            in_questions = "question" in heading
            continue
        if not in_questions:
            continue
        match = re.match(r"^\d+[.)]\s+(.+)$", line)
        if match:
            if current:
                questions.append(" ".join(current))
            current = [match.group(1).strip()]
        elif current and line:
            current.append(line)
    if current:
        questions.append(" ".join(current))
    return questions


def parse_tutor_guidance(response: dict) -> TutorGuidance:
    text = response["candidates"][0]["content"]["parts"][0]["text"]
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(text)
    verdict = str(data.get("verdict", "")).lower()
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict: {verdict!r}")
    feedback = str(data.get("feedback", "")).strip()
    if not feedback:
        raise ValueError("empty tutor feedback")
    usage = response.get("usageMetadata", {})
    return TutorGuidance(
        verdict=verdict,
        feedback=feedback,
        answer_summary=str(data.get("answer_summary", "")).strip(),
        tokens_in=usage.get("promptTokenCount", 0),
        tokens_out=usage.get("candidatesTokenCount", 0),
    )


def record_review(
    tutor: TutorSession,
    *,
    actor: str = "sharat",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """Write one completed score through Hermes' canonical CLI and read it back."""
    if not tutor.complete or tutor.attempted != len(tutor.deck.questions):
        raise HermesError("finish every question before recording the review")
    if tutor.recorded:
        raise HermesError("this review was already recorded")

    event_path = tutor.deck.root / "learning" / tutor.deck.slug / "events.jsonl"
    before = _read_jsonl(event_path)
    notes = "Duet voice review; partial answers count as incorrect in the strict integer score."
    command = [
        "python3",
        "scripts/brain.py",
        "review",
        tutor.deck.slug,
        "--correct",
        str(tutor.strict_correct),
        "--total",
        str(tutor.attempted),
        "--actor",
        actor,
        "--notes",
        notes,
    ]
    completed = runner(command, cwd=tutor.deck.root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise HermesError(f"Hermes review command failed: {detail}")

    after = _read_jsonl(event_path)
    if len(after) != len(before) + 1 or after[-1].get("kind") != "review.completed":
        raise HermesError("Hermes command returned success but the review event could not be verified")
    data = after[-1].get("data", {})
    if data.get("correct") != tutor.strict_correct or data.get("total") != tutor.attempted:
        raise HermesError("recorded Hermes score does not match the completed voice review")
    tutor.recorded = True
    return data


def _review_due_at(run_dir: Path, manifest: dict, today: dt.date) -> dt.date:
    artifacts = manifest.get("artifacts", {})
    events = _read_jsonl(run_dir / str(artifacts.get("events", "events.jsonl")))
    reviews = [event for event in events if event.get("kind") == "review.completed"]
    if not reviews:
        return today
    raw = reviews[-1].get("data", {}).get("due_at")
    try:
        return dt.date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise HermesError(f"invalid review due_at in {run_dir / 'events.jsonl'}: {raw!r}") from exc


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HermesError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HermesError(f"expected a JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise HermesError(f"missing Hermes event log: {path}") from exc
    rows: list[dict] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HermesError(f"invalid JSONL at {path}:{number}") from exc
        if not isinstance(row, dict):
            raise HermesError(f"expected an object at {path}:{number}")
        rows.append(row)
    return rows
