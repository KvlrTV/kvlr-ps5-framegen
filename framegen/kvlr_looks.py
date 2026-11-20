"""KVLR edition: built-in "polish" looks, a finishing pass on the final picture (Looks are drawn last, after
upscaling: framegen/looks_gl.py). Made of the stock nodes only, so share codes, the Looks page and both renderers
need nothing new. Subtle on purpose: they make an upscaled 1080p picture read crisper and more filmic without
changing its colours. Hook (marked KVLR): framegen/looks.py, after BUILTIN.
"""
from __future__ import annotations


def kvlr_looks(_look, node) -> dict:
    return {
        # Local contrast for perceived detail, a light edge sharpen, and fine mono grain, which hides the
        # smoothness and banding upscaling leaves (the eye reads grain as detail).
        "kvlr-polish": _look("KVLR Polish",
                             node("clarity", amount=0.2, size=0.3),
                             node("sharpen", amount=0.2),
                             node("grain", amount=0.1, size=0.9, color=0)),
        # Crisper: more clarity and sharpening, a touch of vibrance, the same fine grain.
        "kvlr-polish-crisp": _look("KVLR Crisp",
                                   node("color", vibrance=0.15),
                                   node("clarity", amount=0.35, size=0.3),
                                   node("sharpen", amount=0.35),
                                   node("grain", amount=0.1, size=0.9, color=0)),
        # Filmic: gentle contrast, softer highlights, a little more grain and the faintest vignette.
        "kvlr-polish-film": _look("KVLR Filmic",
                                  node("color", contrast=0.08, highlights=-0.1, vibrance=0.1),
                                  node("clarity", amount=0.2, size=0.35),
                                  node("sharpen", amount=0.15),
                                  node("grain", amount=0.18, size=1.0, color=0.1),
                                  node("vignette", amount=0.12, size=0.6, softness=0.7)),
        # Only the grain: hides banding and upscaling smoothness, changes nothing else.
        "kvlr-grain": _look("KVLR Grain", node("grain", amount=0.12, size=0.9, color=0)),
    }


# ---------------------------------------------------------------------------------------------- the Polish slider
# Setting "polish" (0-200 %, live, framegen/kvlr_settings.py): the KVLR Polish nodes at that strength, added after
# whatever look is on (or on their own). 100 % is the KVLR Polish look. Hook (marked KVLR): looks.LookState.current.
STEPS = tuple(range(0, 201, 10))


def polish_nodes(percent: float) -> list:
    from .looks import node
    p = max(0.0, min(2.0, float(percent) / 100.0))
    return [node("clarity", amount=round(0.2 * p, 2), size=0.3),
            node("sharpen", amount=round(0.2 * p, 2)),
            node("grain", amount=round(0.1 * p, 2), size=0.9, color=0)]


_cache: dict = {}


def with_polish(look: dict | None, settings) -> dict | None:
    """`look` (or no look) with the Polish slider's nodes after it; the same dict for the same inputs, so the
    renderer's plan is only rebuilt when something changed."""
    percent = int(getattr(settings, "polish", 0) or 0)
    if percent <= 0:
        return look
    key = (id(look), percent)
    hit = _cache.get(key)
    if hit is not None and hit[0] is look:
        return hit[1]
    from .looks import MAX_NODES, normalize
    base = list(look["nodes"]) if look else []
    extra = polish_nodes(percent)
    nodes = base[:MAX_NODES - len(extra)] + extra
    name = f"{look['name']} + Polish {percent}%" if look else f"Polish {percent}%"
    out = normalize({"name": name, "nodes": nodes})
    _cache.clear()
    _cache[key] = (look, out)
    return out


def save_polish() -> dict:
    """Saves what's on now (the look, if on, plus Polish at its strength) as one of the user's own looks, so it can
    be picked again later as a preset. The launcher's Play page "Save as look" runs this."""
    from .looks import BUILTIN, DEFAULT_LOOK, Library
    from .settings import Settings
    settings = Settings.load() if hasattr(Settings, "load") else Settings()
    lib = Library()
    look = (lib.get(settings.look) or BUILTIN[DEFAULT_LOOK]) if getattr(settings, "look_on", False) else None
    percent = int(getattr(settings, "polish", 0) or 0)
    nodes = (list(look["nodes"]) if look else []) + (polish_nodes(percent) if percent > 0 else [])
    if not nodes:
        return {"error": "Nothing to save: Polish is at 0% and no look is on."}
    name = f"My {look['name']} + Polish {percent}%" if look and percent else (
        f"My Polish {percent}%" if percent else f"My {look['name']}")
    look_id = lib.save({"name": name, "nodes": nodes}, None)
    return {"id": look_id, "name": name}


if __name__ == "__main__":
    import json
    import sys
    if sys.argv[1:] == ["save-polish"]:
        try:
            r = save_polish()
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)[:200]}
        print(json.dumps(r))
        sys.exit(1 if "error" in r else 0)
