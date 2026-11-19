"""KVLR edition: capture cards at about 30 fps go on a 60 Hz beat (framegen/kvlr_capture.py Every60)."""
import numpy as np

from framegen.io import Tick, Waiting
from framegen.kvlr_capture import Every60, wrap
from framegen.sources import source_info


class FakeCard:
    def __init__(self, fps, n=6, w=64, h=36):
        self.fps, self.w, self.h = fps, w, h
        self.info = source_info("capture", hz=fps, name="test card")
        self.frames = [np.full((h, w, 3), 10 * i, np.uint8) for i in range(n)]

    def __iter__(self):
        for i, f in enumerate(self.frames):
            if i == 2:
                yield Waiting(0.1, "the card", "")
            yield Tick(f, i / self.fps, i)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Settings:
    capture_work, model, hz, interp, vfg_quality = "auto", "vfg", 120, True, "medium"


def test_every_frame_is_followed_by_one_repeat_half_a_frame_later():
    clock = Clock()
    src = Every60(FakeCard(30), clock=clock, sleep=clock.sleep)
    ticks = [t for t in src if not isinstance(t, Waiting)]
    assert len(ticks) == 12 and [t.index for t in ticks] == list(range(12))
    for real, rep in zip(ticks[0::2], ticks[1::2]):
        assert rep.frame is real.frame and rep.new_hint is False
        assert abs(rep.t_arrival - (real.t_arrival + 1 / 60)) < 1e-9
    assert src.info.hz == 60 and src.fps == 60 and src.repeats == 6
    assert src.w == 64  # everything else is the card's own


def test_a_late_pipeline_gets_the_repeat_at_once():
    clock = Clock()
    clock.t = 100.0  # far behind every frame's arrival
    src = Every60(FakeCard(30, n=2), clock=clock, sleep=clock.sleep)
    ticks = [t for t in src if not isinstance(t, Waiting)]
    assert len(ticks) == 4 and clock.t == 100.0  # never slept


def test_wrap_only_beats_30_fps_capture_cards():
    assert isinstance(wrap(FakeCard(30), Settings(), "capture"), Every60)
    assert not isinstance(wrap(FakeCard(60), Settings(), "capture"), Every60)
    assert not isinstance(wrap(FakeCard(30), Settings(), "chiaki"), Every60)


def test_ntsc_rates_are_asked_for_exactly():
    from framegen.capture import Mode, open_options
    assert open_options(Mode("nv12", True, 1920, 1080, 59.9402, 59.9402))["framerate"] == "59.94"
    assert open_options(Mode("nv12", True, 3840, 2160, 29.97, 29.97), fps=30)["framerate"] == "29.97"
    assert open_options(Mode("yuyv422", True, 1920, 1080, 10, 60.0002))["framerate"] == "60"
    assert open_options(Mode("yuyv422", True, 2560, 1440, 10, 30), fps=30)["framerate"] == "30"
