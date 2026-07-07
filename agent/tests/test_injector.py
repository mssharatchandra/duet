# The injector implements the brief's "crux" rules (see injector.py header):
# 1. never inject over the user  2. the user always wins  3. guidance goes stale.
# Every transition is covered here with a fake tokenizer and a fake clock.

from duet_agent.injector import State, TextInjector

PAD = 3
QUIET, LOUD = 0.0, 0.1


def fake_encode(s: str) -> list[int]:
    return [100 + i for i in range(len(s.split()))]  # one token per word


def make(clock=None, **kw):
    t = {"now": 0.0}

    def now():
        return t["now"]

    inj = TextInjector(encode=fake_encode, pad_ids=(0, PAD), now=now, **kw)
    return inj, t


def quiet_down(inj, frames=6):
    for _ in range(frames):
        inj.on_user_frame(QUIET)


def test_idle_passes_tokens_through():
    inj, _ = make()
    assert inj.hook(42) == 42
    assert inj.state is State.IDLE


def test_waits_for_pad_boundary_and_user_silence():
    inj, _ = make()
    inj.inject("call me maybe")
    assert inj.state is State.ARMED
    assert inj.hook(42) == 42            # mid-word: don't clip Moshi's word
    quiet_down(inj)
    assert inj.hook(42) == 42            # still mid-word even though quiet
    forced_first = inj.hook(PAD)         # pad + quiet → take the floor
    assert forced_first == 100
    assert inj.state is State.FORCING


def test_no_injection_while_user_talking():
    inj, _ = make()
    inj.inject("please hold")
    for _ in range(10):
        inj.on_user_frame(LOUD)          # user mid-sentence
    assert inj.hook(PAD) == PAD          # rule 1: a pad slot while user talks is NOT a slot
    assert inj.state is State.ARMED


def test_forces_full_phrase_then_returns_to_sampling():
    inj, _ = make()
    inj.inject("one two three")
    quiet_down(inj)
    got = [inj.hook(PAD), inj.hook(7), inj.hook(8)]
    assert got == [100, 101, 102]        # sampled tokens ignored while forcing
    assert inj.state is State.IDLE
    assert inj.injected == 1
    assert inj.hook(9) == 9              # free-running again


def test_barge_in_drops_remaining_script():
    inj, _ = make()
    inj.inject("a very long scripted pitch here")
    quiet_down(inj)
    assert inj.hook(PAD) == 100          # forcing started
    for _ in range(4):
        inj.on_user_frame(LOUD)          # lead barges in (~0.3 s)
    assert inj.state is State.IDLE       # rule 2: script dropped, not paused
    assert inj.cancelled_by_barge_in == 1
    assert inj.hook(55) == 55            # model back to native behavior instantly


def test_stale_guidance_is_dropped_unspoken():
    inj, t = make()
    inj.inject("outdated fact")
    quiet_down(inj)
    t["now"] += 9.0                      # conversation moved on past stale_after_s=8
    assert inj.hook(PAD) == PAD          # rule 3
    assert inj.state is State.IDLE
    assert inj.dropped_stale == 1


def test_newer_guidance_replaces_unstarted_older():
    inj, _ = make()
    inj.inject("old point")
    inj.inject("new better point")
    quiet_down(inj)
    assert inj.hook(PAD) == 100
    # 'new better point' = 3 words → 3 tokens; drain and confirm count
    inj.hook(0)
    inj.hook(0)
    assert inj.state is State.IDLE


def test_never_splices_mid_utterance():
    inj, _ = make()
    inj.inject("first pitch")
    quiet_down(inj)
    inj.hook(PAD)                        # forcing 'first'
    inj.inject("second pitch")           # brain got eager — must not clobber
    assert inj.hook(0) == 101            # still finishing the first phrase
    assert inj.state is State.IDLE


def test_pace_pads_interleaved_between_forced_tokens():
    inj, _ = make(pace_pads=2)
    inj.inject("hi there")           # 2 words → tokens 100, 101
    quiet_down(inj)
    got = [inj.hook(PAD) for _ in range(6)]
    assert got == [100, PAD, PAD, 101, PAD, PAD]  # breaths between words
    assert inj.state is State.IDLE
    assert inj.injected == 1
