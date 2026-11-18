"""KVLR edition: stopping from the video window takes a held Esc (or Q) and a confirmation, so a stray key press
never ends the game and the PS5 stream.

- Press Esc: a note counts down while it's held. Let go before HOLD_S seconds: nothing happens.
- Held for HOLD_S seconds: a confirmation, for CONFIRM_S seconds: Enter stops, any other key carries on playing.
- The menu keeps its own Esc (closes the menu) as before.

The video window (io.GLWindowSink) calls on_key() first in its key handler (it gets every press and release) and
tick() once a frame. What the stop then does to the PS5 is the launcher's "When you stop" setting (ps5_on_stop).
"""
from __future__ import annotations

import time

HOLD_S = 5.0
CONFIRM_S = 8.0


def _stop_words(settings) -> str:
    what = getattr(settings, "ps5_on_stop", "end")
    return {"rest": "Stop, end Remote Play and rest the PS5?",
            "keep": "Stop frame generation?"}.get(what, "Stop and end Remote Play?")


class HoldToStop:
    def __init__(self) -> None:
        self.down_at = None  # when Esc went down (held now)
        self.confirm_until = 0.0  # the confirmation is up until then
        self.shown = -1  # the countdown second last shown

    def on_key(self, sink, key: int, action: int) -> bool:
        """True when the key was handled here (the window then does nothing more with it)."""
        glfw = sink.glfw
        now = time.perf_counter()
        stop_key = key in (glfw.KEY_ESCAPE, glfw.KEY_Q)
        if now < self.confirm_until:  # the confirmation is up: Enter stops, anything else carries on
            if action != glfw.PRESS:
                return True
            self.confirm_until = 0.0
            if key in (glfw.KEY_ENTER, glfw.KEY_KP_ENTER):
                sink.toast("Stopping...", 3.0)
                sink.cmd = "quit"
            else:
                sink.toast("Still playing", 1.5)
            return True
        if not stop_key or sink.menu.open:
            return False
        if action == glfw.PRESS:
            self.down_at, self.shown = now, -1
            sink._keyed = True
            self._countdown(sink, now)
        elif action == glfw.RELEASE and self.down_at is not None:
            self.down_at = None
            sink.toast("Hold Esc for 5 seconds to stop", 2.0)
        return True  # REPEAT included: the hold is timed here, not by key repeats

    def tick(self, sink) -> None:
        if self.down_at is None:
            return
        now = time.perf_counter()
        if now - self.down_at >= HOLD_S:
            self.down_at = None
            self.confirm_until = now + CONFIRM_S
            sink.toast(f"{_stop_words(sink.settings)}   Enter: yes    any other key: keep playing", CONFIRM_S)
            return
        self._countdown(sink, now)

    def _countdown(self, sink, now: float) -> None:
        left = max(1, int(HOLD_S - (now - self.down_at) + 0.999))
        if left != self.shown:
            self.shown = left
            sink.toast(f"Keep holding Esc to stop... {left}", 1.5)
