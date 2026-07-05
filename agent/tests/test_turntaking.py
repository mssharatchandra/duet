from duet_agent.turntaking import analyze, spans

F = 0.08  # frame seconds


def track(length: int, *ranges: tuple[int, int]) -> list[bool]:
    t = [False] * length
    for s, e in ranges:
        for i in range(s, e):
            t[i] = True
    return t


def test_spans_merge_short_gaps():
    assert spans(track(20, (2, 5), (6, 9)), merge_gap=3) == [(2, 9)]   # breath merged
    assert spans(track(20, (2, 5), (12, 15)), merge_gap=3) == [(2, 5), (12, 15)]


def test_clean_handoff_no_takeover():
    user = track(100, (10, 30))
    agent = track(100, (33, 60))  # starts 3 frames (240 ms) after user ends
    r = analyze(user, agent)
    assert r.utterances == 1 and r.takeovers == 0
    assert r.takeover_rate == 0.0
    assert r.handoff_ms == [3 * F * 1000]


def test_long_overlap_is_takeover():
    user = track(100, (10, 50))
    agent = track(100, (20, 40))  # starts mid-utterance, lasts 1.6 s
    r = analyze(user, agent)
    assert r.takeovers == 1 and r.backchannels == 0
    assert r.takeover_rate == 1.0
    assert r.overlap_ratio == 20 / 40


def test_short_overlap_is_backchannel_not_takeover():
    user = track(100, (10, 50))
    agent = track(100, (25, 31))  # 6 frames = 0.48 s "mm-hm"
    r = analyze(user, agent)
    assert r.takeovers == 0 and r.backchannels == 1
    assert r.takeover_rate == 0.0


def test_agent_onset_at_utterance_edge_is_not_inside():
    user = track(100, (10, 30))
    agent = track(100, (30, 60))  # instant handoff at the boundary
    r = analyze(user, agent)
    assert r.takeovers == 0
    assert r.handoff_ms == [0.0]


def test_multi_utterance_rate():
    user = track(200, (10, 30), (60, 90), (120, 150))
    agent = track(200, (70, 100), (33, 50))  # one takeover (70), one clean reply (33)
    r = analyze(user, agent)
    assert r.utterances == 3
    assert r.takeovers == 1
    assert r.takeover_rate == 1 / 3
