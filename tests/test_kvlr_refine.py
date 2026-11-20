"""KVLR: the Refine effect (framegen/kvlr_refine.py) and the per-effect Polish sliders (framegen/kvlr_looks.py)."""
import numpy as np

from framegen.looks import node, normalize, render


def _run(img, **kw):
    return render(normalize({"nodes": [node("refine", **kw)]}), img).astype(np.float32)


def _steps(h=96, w=96, slope=0.37):
    """A dark/bright diagonal edge made of 2-pixel stair-steps, as a 1080p edge looks after upscaling to 4K."""
    yy, xx = np.mgrid[0:h, 0:w]
    edge = (yy // 2 * 2) > (xx // 2 * 2) * slope + 20
    img = np.where(edge[..., None], 200, 50).astype(np.uint8)
    return np.repeat(img, 3, -1)


def test_sharpen_raises_detail_without_halos():
    rng = np.random.default_rng(1)
    soft = np.clip(rng.normal(128, 4, (64, 64, 1)), 0, 255).repeat(3, -1).astype(np.uint8)
    soft[:, 32:] += 40
    import cv2
    soft = cv2.GaussianBlur(soft, (0, 0), 1.2)
    out = _run(soft, sharpen=1.0, smooth=0, denoise=0)
    steep = lambda a: np.abs(np.diff(a[..., 1], axis=1))[:, 28:36].max(1).mean()  # the edge's steepest step
    assert steep(out) > steep(soft.astype(np.float32)) * 1.25
    # no halos: never more than a sliver past the neighbourhood's own range
    assert out.max() <= soft.max() + 9 and out.min() >= soft.min() - 9


def test_smooth_edges_fills_in_stair_steps():
    img = _steps()
    out = _run(img, sharpen=0, smooth=1, denoise=0)
    # stair-steps: brightness jumps along each row next to the edge; filling in makes in-between values
    mid = lambda a: ((a[..., 1] > 70) & (a[..., 1] < 180)).sum()
    assert mid(out) > mid(img.astype(np.float32)) * 2


def test_smooth_edges_leaves_texture_alone(monkeypatch):
    # gravel-like texture (blurred noise): no clean edges, so averaging "along" them would paint streaks
    import cv2
    from framegen import kvlr_refine
    rng = np.random.default_rng(3)
    tex = cv2.GaussianBlur(rng.normal(110, 40, (96, 96)).astype(np.float32), (0, 0), 1.0)
    img = np.repeat(np.clip(tex, 0, 255)[..., None], 3, -1).astype(np.uint8)
    moved = lambda: np.abs(_run(img, sharpen=0, smooth=1, denoise=0) - img).mean()
    now = moved()
    monkeypatch.setattr(kvlr_refine, "COH_LO", -2.0)  # the clean-edge check switched off: every edge counts
    monkeypatch.setattr(kvlr_refine, "COH_HI", -1.0)
    assert now < moved() * 0.4


def test_smooth_noise_calms_flat_areas_but_keeps_an_edge():
    rng = np.random.default_rng(2)
    img = np.full((64, 64, 3), 120, np.float32)
    img[:, 32:] = 200
    noisy = np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
    out = _run(noisy, sharpen=0, smooth=0, denoise=1)
    assert out[8:56, 4:26].std() < noisy[8:56, 4:26].astype(np.float32).std() * 0.75
    assert abs(out[:, 36:].mean() - out[:, :28].mean()) > 75  # the edge is still there


def test_polish_sliders_build_the_right_nodes():
    from types import SimpleNamespace
    from framegen.kvlr_looks import polish_name, polish_nodes, with_polish
    s = SimpleNamespace(polish_sharpen=50, polish_edges=0, polish_noise=20, polish_clarity=0, polish_grain=0)
    nodes = polish_nodes(s)
    assert [n["type"] for n in nodes] == ["refine"] and nodes[0]["sharpen"] == 0.6 and nodes[0]["denoise"] == 0.2
    assert polish_name(s) == "Polish Sharpen 50 Noise 20"
    off = SimpleNamespace(polish_sharpen=0, polish_edges=0, polish_noise=0, polish_clarity=0, polish_grain=0)
    assert with_polish(None, off) is None and polish_nodes(off) == []
    s.polish_grain = 100
    assert [n["type"] for n in polish_nodes(s)] == ["refine", "grain"]


def test_the_kvlr_polish_looks_have_no_grain():
    from framegen.looks import BUILTIN
    for key in ("kvlr-polish", "kvlr-polish-crisp"):
        assert "grain" not in [n["type"] for n in BUILTIN[key]["nodes"]]
