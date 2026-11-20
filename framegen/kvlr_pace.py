"""KVLR edition: "Steady 60" (setting "steady_pace"): every frame reaches the screen (and OBS) on an even 60 Hz beat.

Why: at 60 fps output a 30 fps game gives two kinds of tick in turn: an AI frame, which with NVIDIA VFG High takes
most of the 16.7 ms, and a real frame, which is almost free. Shown the moment each is ready, the AI frame goes out
late and the real frame a few ms after it: 60 frames a second on average, but in a late / quick pattern, which looks
juddery on screen and on stream (the OBS feed's "gaps over 25 ms" count showed about half the gaps that long).

How: each frame is shown a fixed delay after its capture frame arrived, so all frames keep the capture's even beat.
- The arrivals go through a phase-locked clock (the card's own 60 Hz, smoothed): USB delivery jitter of a millisecond
  or two doesn't reach the screen. A jump of more than half a frame (a dropped or late frame) re-locks at once.
- The delay follows the work: the 95th percentile of the last two seconds' (ready - beat) plus a 1.5 ms margin,
  between 2 and 30 ms. It rises at once when a frame needs more, and comes down a little at a time.
- A frame that is ready after its time is shown at once (never held back further); the count is logged.
Costs: the cheap real frames wait up to the AI frame's time, so a few ms more delay on them. Only at 60 Hz output
(hook marked KVLR in framegen/pipeline.py, just before each frame is presented).
"""
from __future__ import annotations

import time
from collections import deque

PERIOD = 1.0 / 60.0
MARGIN = 0.0015
MIN_D, MAX_D = 0.002, 0.030
SPIN = 0.0015  # the last part of a wait is spun: Windows' sleep can overshoot by about a millisecond


class Pacer:
    def __init__(self, clock=time.perf_counter, sleep=time.sleep) -> None:
        self.clock, self.sleep = clock, sleep
        self.beat = None  # the smoothed time of the latest capture frame
        self.delay = 0.008
        self.work = deque(maxlen=120)  # (ready - beat) of recent frames, seconds
        self.n = 0
        self.late = 0
        self.last_hold = 0.0  # seconds the last frame was held (the pipeline keeps it out of its timings)
        self.window = [clock(), 0, 0, 0.0]  # start, frames, late, total hold (s)

    def lock(self, t_arrival: float) -> float:
        """The beat for a frame that arrived at t_arrival."""
        if self.beat is None:
            self.beat = t_arrival
            return self.beat
        expect = self.beat + PERIOD
        err = t_arrival - expect
        if abs(err) > PERIOD / 2:
            self.beat = t_arrival  # a dropped, late or repeated-early frame: start again from it
        else:
            self.beat = expect + 0.1 * err
        return self.beat

    def wait(self, t_arrival: float | None) -> None:
        """Called with the frame ready to present: holds it until its place on the beat."""
        self.last_hold = 0.0
        if t_arrival is None:
            return
        beat = self.lock(t_arrival)
        now = self.clock()
        self.work.append(now - beat)
        self.n += 1
        if self.n % 30 == 0 or now - beat + MARGIN > self.delay:
            w = sorted(self.work)
            want = w[min(len(w) - 1, int(0.95 * len(w)))] + MARGIN
            want = min(MAX_D, max(MIN_D, want))
            # up at once, down slowly (a quiet moment shouldn't make the next busy one late)
            self.delay = want if want > self.delay else self.delay - 0.25 * (self.delay - want)
        due = beat + self.delay
        hold = due - now
        w = self.window
        w[1] += 1
        if hold <= 0:
            self.late += 1
            w[2] += 1
        else:
            if hold > SPIN:
                self.sleep(hold - SPIN)
            while self.clock() < due:
                pass
            w[3] += hold
            self.last_hold = hold
        if now - w[0] >= 60.0:
            print(f"[pace] steady 60, last minute: frames shown {1000 * self.delay:.1f} ms after their capture "
                  f"beat, {w[2]} of {w[1]} ready late (shown at once), average hold {1000 * w[3] / max(1, w[1]):.1f} ms")
            self.window = [now, 0, 0, 0.0]


def make(settings, hz: int):
    if hz != 60 or not getattr(settings, "steady_pace", True):
        return None
    return Pacer()


def pace_for(pacer, settings, hz: int):
    """The pacer to use now (made once, dropped when output isn't 60 or Steady 60 is off)."""
    on = hz == 60 and (settings is None or getattr(settings, "steady_pace", True))
    if not on:
        return None
    return pacer if pacer is not None else Pacer()
