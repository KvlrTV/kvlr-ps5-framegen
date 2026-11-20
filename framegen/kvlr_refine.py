"""KVLR edition: the "Refine" look effect, which sharpens and smooths in the same pass.

An upscaled 1080p picture has two faults that pull opposite ways: it is soft (wants sharpening) and it has stair-steps
on diagonal edges and fine noise in flat areas (wants smoothing). Ordinary sharpening makes both of the second worse.
Refine works out, for each pixel, which way the edge through it runs (from the brightness gradient over a few
pixels), then:
- Smooth edges: averages along the edge, which fills in stair-steps without blurring across the edge. Only on clean
  edges: where the brightness also changes a lot along the "edge" it is texture, and averaging there paints streaks.
- Sharpen: sharpens across the edge (and plain detail where there is no edge). It sharpens less where the contrast
  is already high (as AMD's CAS does) and never overshoots its neighbours by more than a sliver, so no halos.
- Smooth noise: an edge-keeping (bilateral) smoothing of small differences in flat areas, and with it on, the
  smallest differences aren't sharpened, so noise isn't brought out while real detail is.

One pass after upscaling, at the window's size (about 34 texture reads a pixel). Both renderers use this file:
start() is the NumPy reference, GLSL the shader function; tests/test_looks.py holds them to each other.
Hooks (marked KVLR): framegen/looks.py TYPES_LIST, uniforms() and _start(); framegen/looks_gl.py _HEAD.
"""
from __future__ import annotations

CODE = 40  # its number in share codes (well clear of the stock types, 1-16)
EDGE_LO, EDGE_HI = 0.03, 0.12  # brightness step across three pixels that starts / fully counts as an edge
R = 1.5  # gradient taps: half-pixel offsets, so each tap is a 2x2 average
# Smooth edges acts only on clean edges: where the gradient two pixels along the edge, both ways, points the same way
# as here (|cos| averaged): at or above COH_HI fully, at or below COH_LO (texture: grain, gravel) not at all.
COH_LO, COH_HI = 0.75, 0.95


def node_type(NodeType, _p):
    return NodeType("refine", CODE, "Refine", "sharpen",
                    "Sharpens and smooths at once: sharper across edges and detail, smoother along edges (fewer "
                    "stair-steps) and in flat areas (less noise). Made for upscaled pictures.",
                    (_p("sharpen", "Sharpen", 0, 2, 0.5), _p("smooth", "Smooth edges", 0, 1, 0.5),
                     _p("denoise", "Smooth noise", 0, 1, 0.25)))


def uniforms(n: dict) -> list:
    return [("sharp", n["sharpen"]), ("aa", n["smooth"]), ("dn", n["denoise"])]


GLSL = f"""
const float COH_LO = {COH_LO}, COH_HI = {COH_HI};
""" + """
vec3 kr_at(vec2 o) { return texture(src, (Q + o) / out_size).rgb; }
float kr_l(vec2 o) { return dot(kr_at(o), W); }
vec2 kr_g(vec2 o) { return vec2(kr_l(o + vec2(1.5, 0.0)) - kr_l(o - vec2(1.5, 0.0)), kr_l(o + vec2(0.0, 1.5)) - kr_l(o - vec2(0.0, 1.5))); }
vec3 s_refine(vec3 c, float sharp, float aa, float dn) {
    ivec2 p = ivec2(Q), m = textureSize(src, 0) - 1;
    float lc = dot(c, W), sig = 0.002 + 0.06 * dn;
    vec3 cmin = c, cmax = c, bs = c, cross = vec3(0.0);
    float ws = 1.0, lmin = lc, lmax = lc;
    for (int dy = -1; dy <= 1; dy++)
        for (int dx = -1; dx <= 1; dx++) {
            if (dx == 0 && dy == 0) continue;
            vec3 v = texelFetch(src, clamp(p + ivec2(dx, dy), ivec2(0), m), 0).rgb;
            float lv = dot(v, W), d = (lv - lc) / sig, w = exp(-d * d);
            cmin = min(cmin, v); cmax = max(cmax, v); lmin = min(lmin, lv); lmax = max(lmax, lv);
            bs += w * v; ws += w;
            if (dx == 0 || dy == 0) cross += v;
        }
    vec3 bil = bs / ws;
    const float r = 1.5;
    float gx = kr_l(vec2(r, -r)) + 2.0 * kr_l(vec2(r, 0.0)) + kr_l(vec2(r, r))
             - kr_l(vec2(-r, -r)) - 2.0 * kr_l(vec2(-r, 0.0)) - kr_l(vec2(-r, r));
    float gy = kr_l(vec2(-r, r)) + 2.0 * kr_l(vec2(0.0, r)) + kr_l(vec2(r, r))
             - kr_l(vec2(-r, -r)) - 2.0 * kr_l(vec2(0.0, -r)) - kr_l(vec2(r, -r));
    vec2 g = vec2(gx, gy);
    float len = length(g);
    vec2 nn = len > 1e-5 ? g / len : vec2(1.0, 0.0);
    vec2 t = vec2(-nn.y, nn.x);
    float we = smoothstep(0.03, 0.12, 0.25 * len);
    vec3 a1 = kr_at(t), b1 = kr_at(-t), a2 = kr_at(2.0 * t), b2 = kr_at(-2.0 * t), a3 = kr_at(3.0 * t), b3 = kr_at(-3.0 * t);
    vec3 sa = (c + a1 + b1 + 0.75 * (a2 + b2) + 0.5 * (a3 + b3)) / 5.5;
    vec3 pn = kr_at(nn), mn = kr_at(-nn);
    vec2 ga = kr_g(2.0 * t), gb = kr_g(-2.0 * t);
    float agree = 0.5 * (abs(dot(ga, nn)) / max(length(ga), 1e-5) + abs(dot(gb, nn)) / max(length(gb), 1e-5));
    float coh = smoothstep(COH_LO, COH_HI, agree);
    vec3 b = mix(c, bil, dn * (1.0 - we));
    b = mix(b, sa, aa * we * coh);
    vec3 d = mix(c - 0.25 * cross, c - 0.5 * (pn + mn), we);
    float amp = sqrt(clamp(min(lmin, 1.0 - lmax) / max(lmax, 1e-4), 0.0, 1.0));
    float gate = mix(1.0, smoothstep(0.004, 0.02, abs(dot(d, W))), dn);
    return clamp(b + 1.5 * sharp * amp * gate * d, cmin - 0.03, cmax + 0.03);
}
"""


def start(u: dict, c, ctx, bilerp, w709):
    """The NumPy reference of s_refine (c: HxWx3 float32 RGB, the pass's input)."""
    import numpy as np
    h, w = c.shape[:2]
    W = np.array(w709, np.float32)
    f = np.float32
    sharp, aa, dn = f(u["sharp"]), f(u["aa"]), f(u["dn"])
    py, px = ctx["qy"] - f(0.5), ctx["qx"] - f(0.5)

    def at(ox, oy):
        return bilerp(c, py + oy, px + ox)

    def lum(ox, oy):
        return at(ox, oy) @ W

    pad = np.pad(c, ((1, 1), (1, 1), (0, 0)), mode="edge")
    lc = c @ W
    sig = f(0.002) + f(0.06) * dn
    cmin, cmax, bs = c.copy(), c.copy(), c.copy()
    ws = np.ones((h, w), np.float32)
    lmin, lmax = lc.copy(), lc.copy()
    cross = np.zeros_like(c)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            v = pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
            lv = v @ W
            d = (lv - lc) / sig
            wt = np.exp(-d * d)
            cmin, cmax = np.minimum(cmin, v), np.maximum(cmax, v)
            lmin, lmax = np.minimum(lmin, lv), np.maximum(lmax, lv)
            bs = bs + wt[..., None] * v
            ws = ws + wt
            if dx == 0 or dy == 0:
                cross = cross + v
    bil = bs / ws[..., None]
    r = f(R)
    gx = lum(r, -r) + 2 * lum(r, 0) + lum(r, r) - lum(-r, -r) - 2 * lum(-r, 0) - lum(-r, r)
    gy = lum(-r, r) + 2 * lum(0, r) + lum(r, r) - lum(-r, -r) - 2 * lum(0, -r) - lum(r, -r)
    ln = np.sqrt(gx * gx + gy * gy)
    big = ln > 1e-5
    safe = np.where(big, ln, 1)
    nx, ny = np.where(big, gx / safe, 1), np.where(big, gy / safe, 0)
    tx, ty = -ny, nx
    x = np.clip((f(0.25) * ln - f(EDGE_LO)) / f(EDGE_HI - EDGE_LO), 0, 1)
    we = (x * x * (3 - 2 * x))[..., None]
    a1, b1, a2, b2 = at(tx, ty), at(-tx, -ty), at(2 * tx, 2 * ty), at(-2 * tx, -2 * ty)
    a3, b3 = at(3 * tx, 3 * ty), at(-3 * tx, -3 * ty)
    sa = (c + a1 + b1 + f(0.75) * (a2 + b2) + f(0.5) * (a3 + b3)) / f(5.5)
    pn, mn = at(nx, ny), at(-nx, -ny)
    def agree(ox, oy):  # |cos| between the gradient there and this pixel's edge normal
        gx = lum(ox + r, oy) - lum(ox - r, oy)
        gy = lum(ox, oy + r) - lum(ox, oy - r)
        return np.abs(gx * nx + gy * ny) / np.maximum(np.sqrt(gx * gx + gy * gy), f(1e-5))
    k = np.clip((f(0.5) * (agree(2 * tx, 2 * ty) + agree(-2 * tx, -2 * ty)) - f(COH_LO)) / f(COH_HI - COH_LO), 0, 1)
    coh = (k * k * (3 - 2 * k))[..., None]
    b = c + (bil - c) * (dn * (1 - we))
    b = b + (sa - b) * (aa * we * coh)
    lap = c - f(0.25) * cross
    acr = c - f(0.5) * (pn + mn)
    d = lap + (acr - lap) * we
    amp = np.sqrt(np.clip(np.minimum(lmin, 1 - lmax) / np.maximum(lmax, f(1e-4)), 0, 1))[..., None]
    g = np.clip((np.abs(d @ W) - f(0.004)) / f(0.016), 0, 1)
    gate = (1 + (g * g * (3 - 2 * g) - 1) * dn)[..., None]
    return np.clip(b + f(1.5) * sharp * amp * gate * d, cmin - f(0.03), cmax + f(0.03))
