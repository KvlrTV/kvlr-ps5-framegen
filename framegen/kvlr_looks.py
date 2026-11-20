"""KVLR edition: built-in "polish" looks, a finishing pass on the final picture (Looks are drawn last, after
upscaling: framegen/looks_gl.py). Made of the stock nodes only, so share codes, the Looks page and both renderers
need nothing new. Subtle on purpose: they make an upscaled 1080p picture read crisper and more filmic without
changing its colours. Hook (marked KVLR): framegen/looks.py, after BUILTIN.
"""
from __future__ import annotations


def kvlr_looks(_look, node) -> dict:
    return {
        # Local contrast for perceived detail, then Refine (framegen/kvlr_refine.py): sharper across edges,
        # smoother along them and in flat areas. No grain (Kev, 2026-11-20: he didn't like it).
        "kvlr-polish": _look("KVLR Polish",
                             node("clarity", amount=0.2, size=0.3),
                             node("refine", sharpen=0.4, smooth=0.5, denoise=0.25)),
        # Crisper: more clarity and sharpening, a touch of vibrance.
        "kvlr-polish-crisp": _look("KVLR Crisp",
                                   node("color", vibrance=0.15),
                                   node("clarity", amount=0.35, size=0.3),
                                   node("refine", sharpen=0.7, smooth=0.6, denoise=0.3)),
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


# ---------------------------------------------------------------------------------------------- the Polish sliders
# One setting per effect (0-100 %, live, framegen/kvlr_settings.py), added after whatever look is on (or on their
# own). Sharpen, Smooth edges and Smooth noise are one Refine pass; Clarity and Grain their own.
# Hook (marked KVLR): looks.LookState.current.
KEYS = ("polish_sharpen", "polish_edges", "polish_noise", "polish_clarity", "polish_grain")
STEPS = tuple(range(0, 101, 5))


def _pc(settings, key: str) -> float:
    try:
        return max(0.0, min(1.0, float(getattr(settings, key, 0) or 0) / 100.0))
    except (TypeError, ValueError):
        return 0.0


def polish_nodes(settings) -> list:
    from .looks import node
    sh, ed, no, cl, gr = (_pc(settings, k) for k in KEYS)
    out = []
    if cl > 0:
        out.append(node("clarity", amount=round(0.4 * cl, 2), size=0.3))
    if sh > 0 or ed > 0 or no > 0:
        out.append(node("refine", sharpen=round(1.2 * sh, 2), smooth=round(ed, 2), denoise=round(no, 2)))
    if gr > 0:
        out.append(node("grain", amount=round(0.2 * gr, 2), size=0.9, color=0))
    return out


def polish_name(settings) -> str:
    names = ("Sharpen", "Edges", "Noise", "Clarity", "Grain")
    parts = [f"{n} {round(100 * _pc(settings, k))}" for n, k in zip(names, KEYS) if _pc(settings, k) > 0]
    return "Polish " + " ".join(parts) if parts else ""


_cache: dict = {}


def with_polish(look: dict | None, settings) -> dict | None:
    """`look` (or no look) with the Polish slider's nodes after it; the same dict for the same inputs, so the
    renderer's plan is only rebuilt when something changed."""
    values = tuple(round(100 * _pc(settings, k)) for k in KEYS)
    if not any(values):
        return look
    key = (id(look), values)
    hit = _cache.get(key)
    if hit is not None and hit[0] is look:
        return hit[1]
    from .looks import MAX_NODES, normalize
    base = list(look["nodes"]) if look else []
    extra = polish_nodes(settings)
    nodes = base[:MAX_NODES - len(extra)] + extra
    name = f"{look['name']} + {polish_name(settings)}" if look else polish_name(settings)
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
    extra = polish_nodes(settings)
    nodes = (list(look["nodes"]) if look else []) + extra
    if not nodes:
        return {"error": "Nothing to save: every Polish slider is at 0% and no look is on."}
    pn = polish_name(settings)
    name = (f"My {look['name']} + {pn}" if look and extra else f"My {pn}" if extra else f"My {look['name']}")[:60]
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
