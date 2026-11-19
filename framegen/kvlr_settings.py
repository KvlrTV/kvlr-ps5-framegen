"""KVLR edition: the settings it adds to SmoovPlay's registry (framegen/settings.py appends these to SPECS).

Kept in its own file so upstream's settings.py changes merge cleanly; settings.py passes in its Spec class, so this
file never imports it (no import loop).
"""
from __future__ import annotations

OBS_SIZES = {"2160": (3840, 2160), "1440": (2560, 1440), "1080": (1920, 1080)}
OBS_SENDER = "KVLR PS5"  # the name OBS's Spout2 Capture source lists
# Set once and changed on the launcher's Settings page (live, while playing too), so they stay out of the in-video
# menu, which has to fit a 1080p picture with room for upstream's next settings (tests/test_settings.py).
MENU_HIDDEN_GROUPS = {"OBS output", "PS5 connection", "Capture card", "Sound"}

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
    from .kvlr_audio import default_choice, outputs
    outs = outputs()
    return (
        Spec("audio_out", "Sound out", ("default",) + outs, default_choice(outs),
             {"default": "Windows default output"} | {n: n for n in outs}, live=False, group="Sound",
             help="Where the game's sound plays: a capture card's sound, which KVLR PS5 Frame Gen plays, and PS5 "
                  "Remote Play's, which chiaki-ng plays (set for it before Play). The default is your BEACN Mix "
                  "Create's Game channel when it's there. Applies from the next Play.",
             hints={"default": "Whatever Windows uses for sound"}),
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
        Spec("dlss_preset", "DLSS model", ("auto", "k", "l", "m"), "auto",
             {"auto": "Auto", "k": "K (quality)", "l": "L (low input sizes)", "m": "M (DLSS 4.5)"}, live=False,
             group="Picture", applies=("scaler", ("dlss",)),
             help="Which DLSS model upscales. Auto lets the driver pick for the size. Applies from the next Play."),
        Spec("dlss_motion", "DLSS motion", ("flow", "zero"), "flow", {"flow": "Optical flow", "zero": "None (still)"},
             live=False, group="Picture", applies=("scaler", ("dlss",)),
             help="How DLSS learns what moved between frames. Optical flow measures it with the graphics card's "
                  "flow hardware, so moving things stay sharp; None treats the picture as still, which can smear "
                  "fast motion. Applies from the next Play.",
             hints={"flow": "Moving things stay sharp", "zero": "Lightest; fast motion can smear"}),
        Spec("dlssg_motion", "DLSS FG motion", ("fine", "balanced", "fast", "smoothed", "none"), "balanced",
             {"fine": "Fine", "balanced": "Balanced", "fast": "Fast", "smoothed": "Smoothed", "none": "None"},
             live=False, group="Smoothness", applies=("model", ("dlssg",)),
             help="How DLSS FG is told what moved: optical flow measured by your graphics card. Fine measures every "
                  "pixel at the best quality (cleanest edges, a little more work); Fast uses 4x4 blocks (blocky edges "
                  "can tear); Smoothed cleans stray vectors up; None leaves it to DLSS FG's own analysis.",
             hints={"fine": "Every pixel, best quality: cleanest edges", "balanced": "2x2 blocks, medium quality",
                    "fast": "4x4 blocks, fast: edges can tear", "smoothed": "4x4, best quality, stray vectors removed",
                    "none": "DLSS FG's own analysis only"}),
        Spec("dlssg_depth", "DLSS FG depth", ("off", "estimated"), "off", {"off": "Off", "estimated": "Estimated"},
             live=False, group="Smoothness", applies=("model", ("dlssg",)),
             help="Estimated depth tells DLSS FG what's in front (your character) and what's behind, so a background "
                  "sliding past doesn't drag the outline with it. An AI model (Depth Anything V2 Small) reads it from "
                  "each real frame: about 4.5 ms per real frame. The first use builds it (about a minute).",
             hints={"off": "Flat: everything at one distance", "estimated": "Depth Anything V2: cleaner outlines"}),
        Spec("dlssg_lite", "DLSS FG lite blending", (False, True), False, on_off,
             live=False, group="Smoothness", applies=("model", ("dlssg",)),
             help="DLSS FG's lighter way of blending its candidate frames. It may soften tearing at edges, at some "
                  "cost to sharpness. Applies after a restart.",
             hints={False: "DLSS FG's normal blending", True: "Lighter blending: softer edges"}),
        Spec("obs_output", "OBS output", (False, True), False, on_off, group="OBS output",
             help="Sends a clean copy of the picture to OBS through Spout: no menu, stats or notes on it. In OBS, "
                  f"add a Spout2 Capture source and pick \"{OBS_SENDER}\" (needs the Spout2 plugin for OBS). "
                  "Off with HDR output.",
             impact={"picture": "None on SmoovPlay's own window.",
                     "speed": "About 0.1 to 0.3 ms a frame of graphics card time, only while it's on."}),
        Spec("obs_stats", "Stats on stream", (False, True), False, on_off, group="OBS output",
             applies=("obs_output", (True,)),
             help="Puts the stats bar (frame rate, game rate, delay) on the OBS feed too, as on your screen, never "
                  "the menu or messages. Needs the stats overlay on (S) and the OBS size the same as the screen's "
                  "(fullscreen on a 4K monitor, 4K feed); otherwise OBS gets the picture only.",
             hints={False: "A clean picture", True: "With the stats bar, as on screen"}),
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
