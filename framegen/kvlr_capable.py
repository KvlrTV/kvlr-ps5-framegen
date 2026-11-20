"""KVLR edition: "capable" frame rate on the stats bar: about how many frames a second this PC could show if output
weren't capped (Output 60 fps), worked out from the last couple of seconds' timings.

Per output frame the pipeline either makes an AI frame (stats.proc_interp_ms) or hands on a real one
(proc_other_ms), then draws it (sink_ms). At output rate R with the game at G fps, R - G of the R frames a second
are AI frames, so it keeps up while  (R - G) * interp + G * other + R * draw <= 1000 ms, which gives
R <= (1000 - G * (other - interp)) / (interp + draw).

Drawing is taken at its 25th percentile: with vsync on, a frame's draw time includes the wait for the screen, which
says nothing about what the PC could do. An estimate, not a promise: more AI frames per real frame also cost the
AI model differently (NVIDIA VFG makes several at once). Hooks (marked KVLR): framegen/pipeline.py's stats text.
"""
from __future__ import annotations

import numpy as np

WINDOW = 120  # ticks: about two seconds at 60 fps


def capable_fps(stats, game_fps: float | None) -> float | None:
    pi, po, dr = stats.proc_interp_ms[-WINDOW:], stats.proc_other_ms[-WINDOW:], stats.sink_ms[-WINDOW:]
    if len(pi) < 10 or not dr or not game_fps:
        return None
    interp, other = float(np.median(pi)), float(np.median(po)) if po else float(np.median(pi))
    draw = float(np.percentile(dr, 25))
    per = interp + draw
    if per <= 0:
        return None
    r = (1000.0 - game_fps * (other - interp)) / per
    return max(float(game_fps), min(r, 360.0))


def may_show(settings) -> bool:
    """NVIDIA's licence forbids publishing NVIDIA VFG benchmark results: with VFG and the stats bar going to OBS
    ("Stats on stream"), the capable rate stays off the bar, which then reaches the stream."""
    if settings is None:
        return True
    return not (getattr(settings, "model", "") == "vfg" and getattr(settings, "obs_output", False)
                and getattr(settings, "obs_stats", False))


def private_text(stats, game_fps, settings, hz: int, enabled: bool) -> str | None:
    """The capable rate when it must stay off the stream (may_show is False): drawn on this PC's screen only, after
    the OBS copy is taken (draw_private)."""
    if not enabled or hz != 60 or may_show(settings):
        return None
    cap = capable_fps(stats, game_fps)
    return None if cap is None else f"cap 60 | capable ~{cap:.0f} (this PC only)"


def draw_private(sink, x0: int, y0: int, dw: int, dh: int) -> None:
    """io.GLWindowSink: the private capable line under the stats overlay, after the OBS copy (so not on stream)."""
    text = getattr(sink, "kvlr_capable_text", None)
    if not text or not getattr(sink, "overlay", False):
        return
    from .io import MiniText, _Panel, _mini
    panel = getattr(sink, "_kvlr_cap_panel", None)
    if panel is None:
        panel = sink._kvlr_cap_panel = _Panel(sink.mini_panel.GL, sink.hdr10)
        sink._kvlr_cap_state = None
    ui = sink._stats_ui(dh)
    state = (text, round(ui, 3))
    if state != sink._kvlr_cap_state:
        panel.update(_mini(MiniText.make([(text, "dim")], ""), ui))
        sink._kvlr_cap_state = state
    stats, m = sink.mini_panel, max(2, int(4 * ui))
    corner = getattr(sink.settings, "overlay_corner", "top_left")
    x = x0 + dw - panel.w - m if corner.endswith("right") else x0 + m
    if corner.startswith("bottom"):  # above the stats
        panel.blit(x, y0 + stats.h + m + panel.h + m)
    else:  # under the stats
        panel.blit(x, y0 + dh - m - stats.h - m)
