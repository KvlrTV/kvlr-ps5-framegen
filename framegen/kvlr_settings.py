"""KVLR edition: the settings it adds to SmoovPlay's registry (framegen/settings.py appends these to SPECS).

Kept in its own file so upstream's settings.py changes merge cleanly; settings.py passes in its Spec class, so this
file never imports it (no import loop).
"""
from __future__ import annotations

OBS_SIZES = {"2160": (3840, 2160), "1440": (2560, 1440), "1080": (1920, 1080)}
OBS_SENDER = "KVLR PS5"  # the name OBS's Spout2 Capture source lists
# Set once and changed on the launcher's Settings page (live, while playing too), so they stay out of the in-video
# menu, which has to fit a 1080p picture with room for upstream's next settings (tests/test_settings.py).
MENU_HIDDEN_GROUPS = {"OBS output", "PS5 connection", "Capture card"}

# chiaki-ng's saved settings (Qt QSettings in the registry). The launcher (installer/launcher/KvlrChiaki.cs) writes the
# "PS5 connection" choices there just before Play starts chiaki-ng.
CHIAKI_KEY = r"Software\Chiaki\Chiaki"


def chiaki_consoles() -> tuple:
    """Nicknames of the consoles registered in chiaki-ng, in its order; () when there are none or no registry."""
    try:
        import winreg
        names = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHIAKI_KEY + r"\registered_hosts") as k:
            n = int(winreg.QueryValueEx(k, "size")[0])
            for i in range(1, n + 1):
                try:
                    with winreg.OpenKey(k, str(i)) as h:
                        name = str(winreg.QueryValueEx(h, "server_nickname")[0]).strip()
                except OSError:
                    continue
                if name and name not in names and name != "ask":
                    names.append(name)
        return tuple(names)
    except (OSError, ValueError, ImportError):
        return ()


def kvlr_specs(Spec, on_off: dict) -> tuple:
    consoles = chiaki_consoles()
    return (
        Spec("ps5_console", "Connect to", ("ask",) + consoles, "ask",
             {"ask": "Ask each time"} | {c: c for c in consoles}, group="PS5 connection",
             help="Play connects to this PS5 by itself: chiaki-ng finds it, wakes it from rest mode if it needs to, "
                  "and goes straight into the stream, then gets out of the way. \"Ask each time\" shows "
                  "chiaki-ng's console list instead. Register a console first (Connect your PS5); Open chiaki-ng "
                  "on that page always shows the list.",
             hints={"ask": "chiaki-ng's console list, as before"} | {c: "One click: wakes it and connects" for c in consoles}),
        Spec("ps5_on_stop", "When you stop", ("end", "rest", "keep"), "end",
             {"end": "End Remote Play", "rest": "End Remote Play and rest the PS5", "keep": "Keep streaming in chiaki-ng"},
             group="PS5 connection",
             help="What Stop (or Esc in the video window) does to the PS5's stream. End Remote Play closes chiaki-ng "
                  "and leaves the PS5 on. With rest, the PS5 also goes into rest mode. Keep streaming leaves "
                  "chiaki-ng's own window playing, without frame generation. While playing, Rest PS5 on the Play "
                  "page does the rest-mode stop once.",
             hints={"end": "Closes chiaki-ng; the PS5 stays on", "rest": "Closes chiaki-ng and the PS5 rests",
                    "keep": "chiaki-ng's window carries on"}),
        Spec("ps5_codec", "Stream codec", ("auto", "h264", "keep"), "auto",
             {"auto": "Auto", "h264": "H.264", "keep": "Leave as set in chiaki-ng"}, group="PS5 connection",
             help="Auto asks the PS5 for H.265, or H.265 HDR when HDR output is on, so the stream always matches "
                  "the HDR setting (a mismatch shows washed-out or magenta colours). H.264 is for older graphics "
                  "cards. Applies from the next Play."),
        Spec("ps5_bitrate", "Stream bitrate", ("100", "50", "30", "keep"), "keep",
             {"100": "100 Mbps", "50": "50 Mbps", "30": "30 Mbps", "keep": "Leave as set in chiaki-ng"},
             group="PS5 connection",
             help="How much picture data the PS5 is asked to send on your home network. Higher means fewer "
                  "compression marks for the AI frames and the upscaler to work from; 100 Mbps suits a wired "
                  "connection, 30 to 50 Mbps a good 5 GHz Wi-Fi. Applies from the next Play."),
        Spec("capture_work", "Frame generation size", ("auto", "native", "1440", "1080"), "auto",
             {"auto": "Auto", "native": "As captured", "1440": "1440p", "1080": "1080p"},
             live=False, group="Capture card",
             help="The size the AI frames are made at; the window and OBS output upscale from it. The size asked of the card is Picture → Capture card resolution. Auto works at "
                  "1080p for 90 and 120 fps, which is what keeps up from a 4K card today, and at 60 fps keeps "
                  "4K with NVIDIA VFG (low or medium) and 1440p with RIFE. Applies from the next Play.",
             hints={"auto": "1080p at 90/120 fps, up to 4K at 60", "native": "Sharpest; won't hold 90/120 from 4K yet",
                    "1440": "Between the two", "1080": "Lightest: best for 90/120"},
             impact={"speed": "RIFE at 4K takes about 15 ms per AI frame on an RTX 5070 Ti, too slow for 90 "
                              "or 120 fps."}),
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
