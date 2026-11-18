"""In-video settings menu: keyboard-driven, drawn as an image that the GL window blits over the video.

Rows come from settings.SPECS, so a new setting shows up here without changes to this file. Drawing happens
only when something on the menu changes (the window caches the image), so an open menu costs nothing per frame.
"""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from .settings import SPECS, Settings, Spec

FONT = cv2.FONT_HERSHEY_SIMPLEX
TITLE_FONT = cv2.FONT_HERSHEY_DUPLEX
# BGR
BG = (34, 30, 28)
ROW_SEL = (70, 58, 48)
ACCENT = (40, 170, 255)
TEXT = (238, 238, 238)
MUTED = (150, 150, 150)
IMPACT = (200, 200, 200)
DIM = (95, 95, 95)
RULE = (70, 66, 62)


class Menu:
    """allowed(key, value): whether a choice can be picked now (e.g. RTX VSR when the SDK isn't installed).
    disabled(key): a reason to grey out a whole row, or None. restart_reasons(): labels of settings changed
    since start that need a restart. Changes go through Settings, whose watchers apply them."""

    def __init__(self, settings: Settings, specs: tuple[Spec, ...] = SPECS,
                 allowed: Callable[[str, object], bool] | None = None,
                 disabled: Callable[[str], str | None] | None = None,
                 restart_reasons: Callable[[], list[str]] | None = None) -> None:
        self.settings, self.specs = settings, specs
        from .kvlr_settings import MENU_HIDDEN_GROUPS  # KVLR: launcher-only settings stay out of the in-video menu
        self.specs = tuple(s for s in self.specs if s.group not in MENU_HIDDEN_GROUPS)
        self.allowed = allowed or (lambda k, v: True)
        self.disabled = disabled or (lambda k: None)
        self.restart_reasons = restart_reasons or (lambda: [])
        self.open = False
        self.index = 0
        self._sel: str | None = None  # the highlighted setting's key, and the index it was at (see _follow)
        self._at = 0
        self._foot_key, self._foot_h = None, 0  # render(): the help area's height, for these rows at this size

    def rows(self) -> list[tuple[str, Spec | None]]:
        """The settings that apply right now (VFG quality only while NVIDIA VFG is picked, and so on)."""
        values = self.settings.values()
        rows: list[tuple[str, Spec | None]] = [("setting", s) for s in self.specs if s.applies_to(values)]
        if self.restart_reasons():
            rows.append(("restart", None))
        return rows

    def _follow(self, rows: list) -> None:
        """Keeps the highlight on the same setting when rows appear or go (a model or upscaler change)."""
        keys = [s.key if s is not None else kind for kind, s in rows]  # "restart" for the Restart now row
        if self.index == self._at and self._sel in keys:  # (index set from outside: that row, as given)
            self.index = keys.index(self._sel)
        self.index = min(self.index, len(rows) - 1)
        self._sel, self._at = keys[self.index], self.index

    def key(self, name: str) -> str | None:
        """name: up / down / left / right / enter / back. Returns "close", "restart" or None."""
        rows = self.rows()
        self._follow(rows)
        if name == "back":
            return "close"
        if name in ("up", "down"):
            self.index = (self.index + (-1 if name == "up" else 1)) % len(rows)
            kind, spec = rows[self.index]
            self._sel, self._at = (spec.key if spec is not None else kind), self.index
            return None
        kind, spec = rows[self.index]
        if kind == "restart":
            return "restart" if name == "enter" else None
        if self.disabled(spec.key):
            return None
        if name in ("left", "right", "enter"):
            self.settings.step(spec.key, -1 if name == "left" else 1, self.allowed)
        return None

    def state(self) -> tuple:
        """Everything the drawing depends on (the window redraws only when this changes)."""
        return (self.index, tuple(self.settings.values().items()), tuple(self.restart_reasons()),
                tuple(self.disabled(s.key) for s in self.specs))

    def render(self, ui: float = 1.0) -> np.ndarray:
        """The menu as a BGR image; ui scales it (1.0 suits a 1080p-tall window)."""
        def px(v: float) -> int:
            return max(1, int(round(v * ui)))

        w, pad, row_h, head_h = px(780), px(26), px(46), px(78)
        fs, small = 0.66 * ui, 0.5 * ui
        th = 1 if ui < 1.4 else 2
        rows = self.rows()
        self._follow(rows)

        def foot(kind, spec) -> tuple[list[str], list[str]]:
            """A row's help under the list, and under that its rough effect on the picture and on speed."""
            if kind == "restart":
                text = "Restarts the pipeline with the new settings. The stream keeps running; takes a few seconds."
            else:
                text = self.disabled(spec.key) or spec.help
            impact: list[str] = []
            if kind != "restart" and not self.disabled(spec.key):
                for k, name in (("picture", "Picture"), ("speed", "Speed")):
                    if spec.impact.get(k):
                        impact += _wrap(f"{name}: {spec.impact[k]}", w - 2 * pad, small, th)[:2]
            return _wrap(text, w - 2 * pad, small, th)[:4], impact

        def foot_size(lines: tuple[list[str], list[str]]) -> int:
            return (len(lines[0]) + len(lines[1])) * px(26) + (px(8) if lines[1] else 0)

        help_lines, impact_lines = foot(*rows[self.index])
        # The help area is as tall as the longest help in the list, whichever row is selected, so the menu keeps its
        # size and the rows stay where they are while the player goes up and down.
        key = (round(ui, 3), tuple((kind, spec.key if spec else None, self.disabled(spec.key) if spec else None)
                                   for kind, spec in rows))
        if self._foot_key != key:
            self._foot_key, self._foot_h = key, max(foot_size(foot(kind, spec)) for kind, spec in rows)
        foot_h = px(18) + self._foot_h + px(46)
        if head_h + len(rows) * row_h + foot_h > px(1040):  # many rows: closer together, so it fits the window
            row_h = max(px(30), (px(1040) - head_h - foot_h) // len(rows))
        h = head_h + len(rows) * row_h + foot_h
        img = np.full((h, w, 3), BG, np.uint8)

        cv2.putText(img, "Settings", (pad, px(50)), TITLE_FONT, 1.05 * ui, TEXT, th + 1, cv2.LINE_AA)
        _text_right(img, "M / Esc to close", w - pad, px(48), small, MUTED, th)
        cv2.line(img, (pad, head_h - px(10)), (w - pad, head_h - px(10)), RULE, max(1, px(1.5)))

        for i, (kind, spec) in enumerate(rows):
            y0 = head_h + i * row_h
            base = y0 + int(row_h * 0.66)
            selected = i == self.index
            if selected:
                cv2.rectangle(img, (0, y0), (w, y0 + row_h - px(2)), ROW_SEL, -1)
                cv2.rectangle(img, (0, y0), (px(6), y0 + row_h - px(2)), ACCENT, -1)
            if kind == "restart":
                reasons = ", ".join(self.restart_reasons())
                cv2.putText(img, f"Restart now  (applies: {reasons})", (pad, base), FONT, fs, ACCENT, th,
                            cv2.LINE_AA)
                continue
            off = self.disabled(spec.key) is not None
            color = DIM if off else TEXT
            cv2.putText(img, spec.label, (pad, base), FONT, fs, color, th, cv2.LINE_AA)
            tag_x = pad + cv2.getTextSize(spec.label, FONT, fs, th)[0][0] + px(12)
            if spec.experimental:  # built without the hardware to test it (as the launcher's EXPERIMENTAL badge)
                cv2.putText(img, "experimental", (tag_x, base), FONT, small * 0.9, DIM if off else ACCENT, th,
                            cv2.LINE_AA)
                tag_x += cv2.getTextSize("experimental", FONT, small * 0.9, th)[0][0] + px(10)
            if not spec.live:
                cv2.putText(img, "restart", (tag_x, base), FONT, small * 0.9, DIM if off else MUTED,
                            th, cv2.LINE_AA)
            value = "not available" if off else spec.name(getattr(self.settings, spec.key))
            right = w - pad
            if selected and not off:
                _text_right(img, ">", right, base, fs, ACCENT, th)
                right -= px(30)
                vw = _text_right(img, value, right, base, fs, TEXT, th)
                _text_right(img, "<", right - vw - px(14), base, fs, ACCENT, th)
            else:
                _text_right(img, value, right - (px(30) if not off else 0), base, fs, MUTED if not off else DIM, th)

        y = head_h + len(rows) * row_h
        cv2.line(img, (pad, y + px(4)), (w - pad, y + px(4)), RULE, max(1, px(1.5)))
        y += px(18)
        for line in help_lines:
            y += px(26)
            cv2.putText(img, line, (pad, y), FONT, small, MUTED, th, cv2.LINE_AA)
        y += px(8) if impact_lines else 0
        for line in impact_lines:
            y += px(26)
            cv2.putText(img, line, (pad, y), FONT, small, IMPACT, th, cv2.LINE_AA)
        cv2.putText(img, "Up/Down select    Left/Right change    M close    Q quit",
                    (pad, h - px(16)), FONT, small * 0.9, DIM, th, cv2.LINE_AA)
        return img


def _text_right(img: np.ndarray, text: str, right: int, base: int, scale: float, color, th: int) -> int:
    tw = cv2.getTextSize(text, FONT, scale, th)[0][0]
    cv2.putText(img, text, (right - tw, base), FONT, scale, color, th, cv2.LINE_AA)
    return tw


def _wrap(text: str, width: int, scale: float, th: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and cv2.getTextSize(trial, FONT, scale, th)[0][0] > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])
