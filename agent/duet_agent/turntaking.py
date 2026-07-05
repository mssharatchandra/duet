# Duet Phase 3 — turn-taking metrics (simplified FullDuplexBench-style).
#
# Input: two parallel boolean tracks sampled on the 80 ms frame grid —
# "user is audibly speaking" and "agent is audibly speaking" — which both the
# real full-duplex loop and the simulated cascade timeline can produce, so the
# metric is mode-agnostic by construction.
#
# Definitions (stated so the benchmark is criticizable, which is the point):
#   utterance    — contiguous user-active span; gaps <0.24 s merged (breaths).
#   TAKEOVER     — agent speech STARTING inside a user utterance and lasting
#                  >0.6 s: grabbing the floor, the "talking over you" failure.
#   backchannel  — agent speech starting inside a user utterance lasting ≤0.6 s
#                  ("mm-hm"): the *good* kind of overlap, counted separately.
#   handoff      — user utterance end → next agent speech onset (ms). This is
#                  the perceived response latency, measured identically for
#                  both modes.
#   overlap      — fraction of user-active frames where the agent is also
#                  active. High overlap + high takeovers = rude bot.

from dataclasses import dataclass

import numpy as np


@dataclass
class TurnTakingReport:
    utterances: int
    takeovers: int
    backchannels: int
    takeover_rate: float
    overlap_ratio: float
    handoff_ms: list[float]

    def summary(self) -> dict:
        p = np.percentile
        return {
            "user_utterances": self.utterances,
            "takeovers": self.takeovers,
            "backchannels": self.backchannels,
            "takeover_rate": round(self.takeover_rate, 4),
            "overlap_ratio": round(self.overlap_ratio, 4),
            "response_latency_ms_p50": round(float(p(self.handoff_ms, 50)), 1) if self.handoff_ms else None,
            "response_latency_ms_p95": round(float(p(self.handoff_ms, 95)), 1) if self.handoff_ms else None,
        }


def spans(active: list[bool], merge_gap: int) -> list[tuple[int, int]]:
    """Contiguous True runs as [start, end) frame pairs, merging short gaps."""
    out: list[list[int]] = []
    for i, a in enumerate(active):
        if not a:
            continue
        if out and i - out[-1][1] <= merge_gap:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return [(s, e) for s, e in out]


def analyze(
    user: list[bool],
    agent: list[bool],
    frame_s: float = 0.08,
    merge_gap_s: float = 0.24,
    backchannel_max_s: float = 0.6,
) -> TurnTakingReport:
    gap = max(1, round(merge_gap_s / frame_s))
    user_spans = spans(user, gap)
    agent_spans = spans(agent, gap)

    takeovers = backchannels = 0
    for a_start, a_end in agent_spans:
        # onset strictly inside a user utterance (not at its edge)
        if any(u_start < a_start < u_end for u_start, u_end in user_spans):
            if (a_end - a_start) * frame_s <= backchannel_max_s:
                backchannels += 1
            else:
                takeovers += 1

    handoffs: list[float] = []
    for _, u_end in user_spans:
        onsets = [a_start for a_start, _ in agent_spans if a_start >= u_end]
        if onsets:
            handoffs.append((onsets[0] - u_end) * frame_s * 1000)

    n = len(user_spans)
    both = sum(1 for u, a in zip(user, agent) if u and a)
    user_frames = max(sum(user), 1)
    return TurnTakingReport(
        utterances=n,
        takeovers=takeovers,
        backchannels=backchannels,
        takeover_rate=takeovers / n if n else 0.0,
        overlap_ratio=both / user_frames,
        handoff_ms=handoffs,
    )
