"""Turn assembly above provider VAD.

Speech APIs emit *acoustic* segments.  A thoughtful speaker can pause long
enough to close one segment and then continue the same sentence.  Treating
every provider END_SPEECH as a conversational turn makes an agent interrupt
people precisely when they are thinking.  This small state machine merges
nearby transcript segments and exposes one provider-independent turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TurnAssembler:
    continuation_grace_s: float = 0.45
    hesitation_grace_s: float = 1.0
    discourse_grace_s: float = 2.1
    speaking: bool = False
    fragments: list[str] = field(default_factory=list)
    deadline: float | None = None

    def speech_started(self) -> None:
        self.speaking = True
        self.deadline = None

    def speech_ended(self, now: float) -> None:
        self.speaking = False
        if self.fragments:
            self._arm_deadline(now)

    def add_transcript(self, text: str, now: float) -> None:
        text = text.strip()
        if not text:
            return
        # Some providers revise a partial by returning the full accumulated
        # text. Replace instead of duplicating in that case; otherwise this is
        # a new acoustic segment belonging to the same possible thought.
        joined = " ".join(self.fragments)
        if joined and text.casefold().startswith(joined.casefold()):
            self.fragments = [text]
        elif not joined.casefold().endswith(text.casefold()):
            self.fragments.append(text)
        if not self.speaking:
            self._arm_deadline(now)

    def poll(self, now: float) -> str | None:
        if self.speaking or self.deadline is None or now < self.deadline:
            return None
        text = _join_fragments(self.fragments)
        self.fragments.clear()
        self.deadline = None
        return text or None

    def reset(self) -> None:
        self.speaking = False
        self.fragments.clear()
        self.deadline = None

    def _arm_deadline(self, now: float) -> None:
        text = _join_fragments(self.fragments)
        if _is_discourse_fragment(text):
            grace = self.discourse_grace_s
        else:
            grace = self.hesitation_grace_s if _looks_incomplete(text) else self.continuation_grace_s
        self.deadline = now + grace


def _is_discourse_fragment(text: str) -> bool:
    """Fragments commonly emitted while a speaker is reformulating a thought."""
    normalized = " ".join(re.findall(r"[a-z']+", text.casefold()))
    return normalized in {
        "actually", "well", "wait", "sorry", "i mean", "let me think", "one second",
        "but actually", "no actually",
    }


def _looks_incomplete(text: str) -> bool:
    """Use a longer pause window when the transcript signals continuation."""
    normalized = text.strip().casefold()
    if not normalized:
        return False
    if normalized.endswith((",", ":", ";", "-", "—", "…", "...")):
        return True
    words = re.findall(r"[a-z']+", normalized)
    if not words:
        return False
    trailing_words = {
        "a", "an", "and", "because", "but", "for", "if", "like", "of", "or",
        "so", "that", "the", "then", "to", "uh", "um", "with",
    }
    if words[-1] in trailing_words:
        return True
    return normalized.rstrip(".?!").endswith(("i think", "i'm not sure", "maybe"))


def _join_fragments(fragments: list[str]) -> str:
    if not fragments:
        return ""
    text = fragments[0].strip()
    for fragment in fragments[1:]:
        fragment = fragment.strip()
        # Acoustic VAD often splits exactly before a hesitation. Preserve the
        # filler as part of the sentence instead of producing "the Uh".
        if text and text[-1] not in ".?!" and re.match(r"(?i)^(uh|um|erm|er)\b", fragment):
            fragment = fragment[:1].lower() + fragment[1:]
            text = text.rstrip(", ") + ", " + fragment
        else:
            text = f"{text} {fragment}".strip()
    return text
