# Duet Phase 2 — text-stream injection: how the slow brain speaks through the fast mouth.
#
# Mechanism (validated against Kyutai's own TTS engine, which forces text the
# same way): LmGen calls an on_text_hook AFTER sampling each frame's text token
# but BEFORE the depformer generates that frame's audio conditioned on it.
# Overwrite the token → Moshi *speaks that word*, in its own voice and prosody.
# We queue a tokenized talking point and feed it in one token per 80 ms frame.
#
# The crux the brief asked about — what happens when async guidance is slow or
# the user won't stop talking — is all here, as three rules:
#
#   1. NEVER inject over the user. Forcing only starts once the model hits a
#      word boundary (a pad token — it isn't mid-word) AND the user has been
#      quiet for ~half a second. Until then Moshi free-runs: it backchannels,
#      finishes its clause, holds the floor naturally. Slow guidance therefore
#      sounds like a person taking a beat, not like buffering.
#   2. The user always wins. If the lead barges in while we're forcing, the
#      remaining script is DROPPED (not paused): the model snaps back to
#      native full-duplex behavior. Resuming a stale pitch after an
#      interruption is exactly the robotic behavior Duet exists to kill.
#   3. Guidance goes stale. If a talking point waited so long for a slot that
#      the conversation moved on, it's discarded unspoken.
#
# NOTE: this gating is *presentation timing* for injected content only — the
# model's own listening/speaking never gates on it (that would rebuild a
# cascade). Pure Python, no MLX: the mx glue lives in sdr_loop.py.

import time
from collections import deque
from enum import Enum
from typing import Callable


class State(Enum):
    IDLE = "idle"          # nothing to say from the brain
    ARMED = "armed"        # phrase queued, waiting for a polite slot
    FORCING = "forcing"    # feeding tokens, one per frame


class TextInjector:
    def __init__(
        self,
        encode: Callable[[str], list[int]],
        pad_ids: tuple[int, ...] = (0, 3),
        quiet_frames_to_start: int = 6,    # ~0.5 s of user silence before we take a slot
        barge_frames_to_cancel: int = 4,   # ~0.3 s of user speech kills the script
        user_rms_threshold: float = 0.02,
        stale_after_s: float = 8.0,
        now: Callable[[float], float] | None = None,
    ):
        self._encode = encode
        self._pad_ids = pad_ids
        self._quiet_needed = quiet_frames_to_start
        self._barge_needed = barge_frames_to_cancel
        self._rms_threshold = user_rms_threshold
        self._stale_after_s = stale_after_s
        self._now = now or time.monotonic

        self.state = State.IDLE
        self._tokens: deque[int] = deque()
        self._queued_at = 0.0
        self._quiet_run = 0
        self._loud_run = 0
        # counters for the exit report / Phase 3 metrics
        self.injected = 0
        self.cancelled_by_barge_in = 0
        self.dropped_stale = 0

    # -- brain side ----------------------------------------------------------

    def inject(self, phrase: str) -> None:
        """Queue a talking point. Latest guidance wins: a newer one replaces an
        un-started older one (the brain knows more now than it did then)."""
        if self.state == State.FORCING:
            return  # never splice mid-utterance; current point finishes first
        self._tokens = deque(self._encode(" " + phrase.strip()))
        self._queued_at = self._now()
        self.state = State.ARMED

    # -- audio side, called once per 80 ms frame ------------------------------

    def on_user_frame(self, rms: float) -> None:
        """Track whether the lead is talking. Cheap energy proxy — deliberately
        NOT a VAD driving turn-taking; it only times/aborts injected content."""
        if rms >= self._rms_threshold:
            self._quiet_run = 0
            self._loud_run += 1
        else:
            self._quiet_run += 1
            self._loud_run = 0
        if self.state == State.FORCING and self._loud_run >= self._barge_needed:
            self._tokens.clear()
            self.state = State.IDLE
            self.cancelled_by_barge_in += 1  # rule 2: the user always wins

    def hook(self, sampled_token: int) -> int:
        """The on_text_hook body: given the token Moshi sampled for this frame,
        return the token that should actually be used."""
        if self.state == State.ARMED:
            if self._now() - self._queued_at > self._stale_after_s:
                self._tokens.clear()
                self.state = State.IDLE
                self.dropped_stale += 1  # rule 3: too late, conversation moved on
                return sampled_token
            if sampled_token in self._pad_ids and self._quiet_run >= self._quiet_needed:
                self.state = State.FORCING  # rule 1: polite slot found — take the floor
            else:
                return sampled_token  # keep free-running (Moshi backfills naturally)
        if self.state == State.FORCING:
            forced = self._tokens.popleft()
            if not self._tokens:
                self.state = State.IDLE
                self.injected += 1
            return forced
        return sampled_token
