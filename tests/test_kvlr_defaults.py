"""KVLR: Kev's settings are the defaults for a new install (framegen/kvlr_settings.py KVLR_DEFAULTS, Settings.load)."""
import json

from framegen.kvlr_settings import KVLR_DEFAULTS
from framegen.settings import BY_KEY, Settings


def test_a_new_settings_file_gets_kevs_settings(tmp_path):
    s = Settings.load(tmp_path / "missing.json")
    for k, v in KVLR_DEFAULTS.items():
        if v in BY_KEY[k].choices:  # e.g. the console only where it's paired
            assert getattr(s, k) == v, k
    assert s.overlay_corner == "top_right" and s.model == "vfg" and s.polish_sharpen == 0


def test_saved_values_still_win(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"overlay_corner": "bottom_left", "model": "4.22.lite"}), encoding="utf-8")
    s = Settings.load(p)
    assert s.overlay_corner == "bottom_left" and s.model == "4.22.lite" and s.vsync is True
