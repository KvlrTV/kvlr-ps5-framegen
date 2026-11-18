"""KVLR edition: the settings it adds to SmoovPlay's registry (framegen/settings.py appends these to SPECS).

Kept in its own file so upstream's settings.py changes merge cleanly; settings.py passes in its Spec class, so this
file never imports it (no import loop).
"""
from __future__ import annotations

OBS_SIZES = {"2160": (3840, 2160), "1440": (2560, 1440), "1080": (1920, 1080)}
OBS_SENDER = "KVLR PS5"  # the name OBS's Spout2 Capture source lists
# Set once and changed on the launcher's Settings page (live, while playing too), so they stay out of the in-video
# menu, which has to fit a 1080p picture with room for upstream's next settings (tests/test_settings.py).
MENU_HIDDEN_GROUPS = {"OBS output"}


def kvlr_specs(Spec, on_off: dict) -> tuple:
    return (
        Spec("obs_output", "OBS output", (False, True), False, on_off, group="OBS output",
             help="Sends a clean copy of the picture to OBS through Spout: no menu, stats or notes on it. In OBS, "
                  f"add a Spout2 Capture source and pick \"{OBS_SENDER}\" (needs the Spout2 plugin for OBS). "
                  "Off with HDR output.",
             impact={"picture": "None on SmoovPlay's own window.",
                     "speed": "About 0.1 to 0.3 ms a frame of graphics card time, only while it's on."}),
        Spec("obs_size", "OBS output size", ("2160", "1440", "1080"), "2160",
             {"2160": "4K (3840x2160)", "1440": "1440p", "1080": "1080p"}, group="OBS output",
             applies=("obs_output", (True,)),
             help="The size OBS gets. When SmoovPlay's picture is already this size (fullscreen on a 4K monitor) "
                  "OBS gets exactly what you see, look included; otherwise it's upscaled with FSR 1 on its own, "
                  "without the look."),
        Spec("obs_fps", "OBS output frame rate", (60, 30), 60, {60: "60 fps", 30: "30 fps"}, group="OBS output",
             applies=("obs_output", (True,)),
             help="How often OBS gets a new picture. At 90 or 120 fps output, frames in between are left out "
                  "for OBS only."),
    )
