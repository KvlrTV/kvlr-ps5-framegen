"""KVLR: Kev's settings are the defaults for a new install (framegen/kvlr_settings.py KVLR_DEFAULTS, Settings.load)."""
import json

from framegen import vfg_setup
from framegen.kvlr_settings import KVLR_DEFAULTS
from framegen.settings import BY_KEY, Settings


def test_a_new_settings_file_gets_kevs_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(vfg_setup, "installed", lambda folder=None: True)  # NVIDIA VFG set up on this PC
    s = Settings.load(tmp_path / "missing.json")
    for k, v in KVLR_DEFAULTS.items():
        if v in BY_KEY[k].choices:  # e.g. the console only where it's paired
            assert getattr(s, k) == v, k
    assert s.overlay_corner == "top_right" and s.model == "vfg" and s.polish_sharpen == 0


def test_without_vfg_the_stock_model_stays(tmp_path, monkeypatch):
    # a friend's PC that hasn't set up NVIDIA VFG (an opt-in download): RIFE, not a model that isn't there
    monkeypatch.setattr(vfg_setup, "installed", lambda folder=None: False)
    s = Settings.load(tmp_path / "missing.json")
    assert s.model == BY_KEY["model"].default and s.vfg_quality == BY_KEY["vfg_quality"].default
    assert s.overlay_corner == "top_right"  # the rest of Kev's settings still apply


def test_saved_values_still_win(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"overlay_corner": "bottom_left", "model": "4.22.lite"}), encoding="utf-8")
    s = Settings.load(p)
    assert s.overlay_corner == "bottom_left" and s.model == "4.22.lite" and s.vsync is True
