"""KVLR: Steady 60 (framegen/kvlr_pace.py) turns a late / quick AI-real pattern into an even 60 Hz beat."""
import random

from framegen.kvlr_pace import PERIOD, Pacer


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1e-5  # each read moves time on a little (the spin loop ends)
        return self.t

    def sleep(self, s):
        self.t += s


def _run(paced: bool, n: int = 1200, slow: float = 0.014, quick: float = 0.001):
    rnd = random.Random(1)
    clock = Clock()
    pacer = Pacer(clock=clock, sleep=clock.sleep) if paced else None
    shown = []
    for i in range(n):
        arrival = i * PERIOD + rnd.uniform(-0.0015, 0.0015)
        clock.t = max(clock.t, arrival)  # the frame arrives (or we were still busy)
        clock.t += slow if i % 2 == 0 else quick  # AI frame, then real frame
        if pacer is not None:
            pacer.wait(arrival)
        shown.append(clock.t)
    gaps = [b - a for a, b in zip(shown[200:], shown[201:])]
    return gaps, pacer


def test_unpaced_is_late_quick():
    gaps, _ = _run(False)
    assert sum(g > 0.025 for g in gaps) > 0.3 * len(gaps)  # the pattern the OBS log showed


def test_steady_60_is_even():
    gaps, pacer = _run(True)
    assert all(abs(g - PERIOD) < 0.002 for g in gaps), (min(gaps), max(gaps))
    assert pacer.late < 20  # only while it learned the delay
    assert 0.014 < pacer.delay < 0.020  # just over the slow frame


def test_a_dropped_frame_relocks():
    p = Pacer(clock=Clock(), sleep=lambda s: None)
    p.lock(0.0)
    p.lock(PERIOD)
    assert p.lock(3 * PERIOD + 0.001) == 3 * PERIOD + 0.001  # a frame missing: start again from the new one
