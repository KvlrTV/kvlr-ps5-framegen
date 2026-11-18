"""30 fps games that dip: a frame the game misses stays on the 60 Hz stream for a third tick (50 ms, not 33). CPU
only: a stand-in interpolator blends its two frames' numbers, and each game frame's number is its time in ticks, so
on screen the numbers should only ever go up."""
import random
import time

import torch

from framegen.io import Tick
from framegen.pipeline import Pipeline
from framegen.settings import Settings


class _Interp:
    h = w = 8
    device = "cpu"
    private = False

    def __init__(self):
        self.in_u8 = torch.zeros(8, 8, 3)
        self.slots = [0.0, 0.0]

    def load(self, frame):
        self.in_u8 = frame

    def prepare(self, slot):
        self.slots[slot] = float(self.in_u8[0, 0, 0])

    def interpolate(self, slot, t=0.5):
        a, b = self.slots[1 - slot], self.slots[slot]
        return torch.full((8, 8, 3), a + t * (b - a))


class _Sink:
    gpu = False

    def __init__(self):
        self.shown = []

    def write(self, frame, text=None):
        f = frame if torch.is_tensor(frame) else torch.as_tensor(frame)
        self.shown.append(float(f[0, 0, 0]))


def _pipeline(interp):
    from framegen import pipeline as pl
    p = Pipeline.__new__(Pipeline)  # no pinned memory: that would start CUDA
    p.interp, p.detector, p.cut_threshold, p.stats = interp, pl.DuplicateDetector(), 25.0, None
    p._out_pinned = torch.empty((8, 8, 3))  # float, so the blends aren't rounded
    p._out_np = p._out_pinned
    return p


def _dipping_game(frames=150, held3=0.3, seed=1):
    """A 30 fps game on a 60 Hz stream that misses about held3 of its frames, as Remote Play sends it: compressed
    sizes (a new frame big, a repeat small) and the stream's frame numbers."""
    rnd = random.Random(seed)
    i = t = 0
    for _ in range(frames):
        ticks = 3 if rnd.random() < held3 else 2
        for k in range(ticks):
            yield Tick(torch.full((8, 8, 3), float(t)), time.perf_counter(), i, new_hint=(k == 0),
                       extra={"size": 9000 if k == 0 else 300, "seq": i})
            i += 1
        t += ticks


def _backward_steps(shown):
    return sum(1 for a, b in zip(shown, shown[1:]) if b < a - 1e-6)


def test_the_30_fps_setting_never_steps_back_when_the_game_dips():
    for hz in (60, 90, 120):
        it, sink = _Interp(), _Sink()
        _pipeline(it).run(_dipping_game(), sink, label="RIFE",
                          settings=Settings({"hz": hz, "even_out": False, "overlay": False, "game_fps": "30"}))
        assert len(sink.shown) > 300
        assert _backward_steps(sink.shown) == 0, hz


def test_auto_never_steps_back_when_the_game_dips():
    it, sink = _Interp(), _Sink()
    _pipeline(it).run(_dipping_game(), sink, label="RIFE",
                      settings=Settings({"hz": 90, "even_out": False, "overlay": False}))
    assert _backward_steps(sink.shown) == 0


def test_a_steady_30_fps_game_is_unchanged_by_the_30_fps_setting():
    shown = {}
    for fps in ("auto", "30"):
        it, sink = _Interp(), _Sink()
        _pipeline(it).run(_dipping_game(held3=0.0), sink, label="RIFE",
                          settings=Settings({"hz": 90, "even_out": False, "overlay": False, "game_fps": fps}))
        shown[fps] = sink.shown
    assert shown["30"][40:] == shown["auto"][40:]  # (after the lock has found the rhythm)
