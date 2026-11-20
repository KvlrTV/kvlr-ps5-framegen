"""KVLR edition: which Windows output the game's sound plays on (setting "audio_out", on the Play page).

A capture card's sound is played by the pipeline (framegen.audio.Player), upstream always on Windows' default output;
here on the output picked (default: the BEACN Mix Create's "Game" channel when the PC has it). For PS5 Remote Play,
chiaki-ng plays the sound: the launcher writes the same pick into chiaki-ng's "audio_out_device" before Play
(installer/launcher/KvlrChiaki.cs). Hook (marked KVLR) in run.py where the capture card's sound player is made.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

PREFERRED = "Game (2- BEACN Mix Create)"  # Kev's stream mix: the game channel


def outputs() -> tuple:
    """Windows' sound outputs under WASAPI, by name, in Windows' order (no duplicates); () if they can't be listed."""
    try:
        import sounddevice as sd
        names = []
        for api in sd.query_hostapis():
            if "WASAPI" not in api["name"]:
                continue
            for i in api["devices"]:
                d = sd.query_devices(i)
                if d["max_output_channels"] > 0 and d["name"] not in names:
                    names.append(d["name"])
        return tuple(names)
    except Exception:  # noqa: BLE001 - no sounddevice / PortAudio: just Windows' default
        return ()


def default_choice(names: tuple) -> str:
    if PREFERRED in names:
        return PREFERRED
    beacn_game = [n for n in names if n.startswith("Game (") and "BEACN" in n]
    return beacn_game[0] if beacn_game else "default"


def device_index(name: str) -> int | None:
    """The WASAPI device index of output `name`, or None (Windows' default)."""
    if not name or name == "default":
        return None
    try:
        import sounddevice as sd
        for api in sd.query_hostapis():
            if "WASAPI" not in api["name"]:
                continue
            for i in api["devices"]:
                d = sd.query_devices(i)
                if d["max_output_channels"] > 0 and d["name"] == name:
                    return i
    except Exception:  # noqa: BLE001
        pass
    return None


def chosen(settings_arg: str) -> str:
    """The saved "audio_out" (read before run.py loads the settings, as the capture source opens first)."""
    names = outputs()
    try:
        v = json.loads(Path(settings_arg).read_text(encoding="utf-8-sig")).get("audio_out")
    except (OSError, ValueError, AttributeError, TypeError):
        v = None
    if v is None:
        return default_choice(names)
    return v if v == "default" or v in names else "default"


def player(Player, settings_arg: str):
    """The sound player class, opened on the chosen output (Windows' default if it's gone)."""
    if Player is None or not callable(Player) or not settings_arg:
        return Player  # no settings file (tests, direct runs): upstream's Windows default output
    name = chosen(settings_arg)
    idx = device_index(name)
    print(f"[capture] sound out: {name if idx is not None else 'Windows default output'}")
    return Player if idx is None else functools.partial(Player, device=idx)
