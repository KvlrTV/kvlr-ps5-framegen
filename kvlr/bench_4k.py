"""How fast frame generation runs at capture-card sizes on this PC, to plan 4K capture with steady 60/90/120 fps.

    python kvlr/bench_4k.py [--sizes 1920x1080,2560x1440,3840x2160] [--no-trt]

For each size: NVIDIA VFG at each quality (when FRAMEGEN_VFX_PATH points at it), and RIFE 4.22.lite at full, half
and quarter motion detail with PyTorch and TensorRT (TensorRT builds an engine per size the first time, a minute or
two each). Each time is split into "prepare" (once per new real frame) and "interp" (once per AI frame), because a
30 fps game needs 1 AI frame per real frame at 60 fps, 2 at 90 and 3 at 120:
    budget per real frame (ms) = 1000/30 = 33.3, needed = prepare + n * interp + the display's own work.
Prints a table and writes installer/build/bench_4k.json (not in git: NVIDIA's licence forbids publishing VFG results).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _pattern(w: int, h: int):
    import torch
    import torch.nn.functional as F
    g = torch.Generator(device="cuda").manual_seed(1)
    small = torch.randint(0, 256, (1, 3, h // 16, w // 16), dtype=torch.uint8, device="cuda", generator=g)
    a = F.interpolate(small.float(), size=(h, w), mode="bilinear", align_corners=False).round().to(torch.uint8)
    a = a[0].permute(1, 2, 0).contiguous()
    return a, torch.roll(a, shifts=(6, 14), dims=(0, 1))


def _time(fn, rounds: int = 6, n: int = 10) -> float:
    import torch
    s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    out = []
    for r in range(rounds):
        torch.cuda.synchronize()
        s.record()
        for _ in range(n):
            fn()
        e.record()
        torch.cuda.synchronize()
        if r >= 2:
            out.append(s.elapsed_time(e) / n)
    return sorted(out)[len(out) // 2]


def measure(it, a, b) -> dict:
    it.load(a)
    it.prepare(0)
    it.load(b)
    it.prepare(1)
    for _ in range(3):
        it.interpolate(1, 0.5)
    prep = _time(lambda: it.prepare(1))
    interp = _time(lambda: it.interpolate(1, 0.5))
    return {"prepare_ms": round(prep, 2), "interp_ms": round(interp, 2)}


def verdict(r: dict) -> dict:
    """Which output rates fit, for a 30 fps game: prepare + n AI frames inside 33.3 ms, with 25% kept for the rest
    of the frame's work (capture upload, display, upscale)."""
    budget = 1000 / 30 * 0.75
    return {hz: r["prepare_ms"] + n * r["interp_ms"] <= budget for hz, n in ((60, 1), (90, 2), (120, 3))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1920x1080,2560x1440,3840x2160")
    ap.add_argument("--no-trt", action="store_true")
    a = ap.parse_args()
    import os

    import torch

    from framegen.interpolator import RifeInterpolator
    results = []
    gpu = torch.cuda.get_device_name(0)
    print(f"[bench] {gpu}")
    for size in a.sizes.split(","):
        w, h = map(int, size.split("x"))
        fa, fb = _pattern(w, h)
        if os.environ.get("FRAMEGEN_VFX_PATH"):
            from framegen.vfg import VfgInterpolator
            for q in ("low", "medium", "high"):
                try:
                    it = VfgInterpolator(w, h, q)
                    r = {"size": size, "engine": f"VFG {q}", **measure(it, fa, fb)}
                    it.close()
                except Exception as ex:  # noqa: BLE001
                    r = {"size": size, "engine": f"VFG {q}", "error": str(ex)[:160]}
                results.append(r)
                print(f"[bench] {r}", flush=True)
                torch.cuda.empty_cache()
        for backend in (("torch",) if a.no_trt else ("torch", "trt")):
            for scale in (1.0, 0.5, 0.25):
                t0 = time.time()
                try:
                    it = RifeInterpolator(w, h, "4.22.lite", scale, backend=backend, build_engine=True)
                    r = {"size": size, "engine": f"RIFE {backend} x{scale}", **measure(it, fa, fb)}
                except Exception as ex:  # noqa: BLE001
                    r = {"size": size, "engine": f"RIFE {backend} x{scale}", "error": str(ex)[:160]}
                r["setup_s"] = round(time.time() - t0, 1)
                results.append(r)
                print(f"[bench] {r}", flush=True)
                it = None
                torch.cuda.empty_cache()
    for r in results:
        if "error" not in r:
            r["fits"] = verdict(r)
    (ROOT / "installer" / "build" / "bench_4k.json").write_text(json.dumps({"gpu": gpu, "results": results}, indent=2))
    print("\nsize       engine                prepare  interp   60   90  120")
    for r in results:
        if "error" in r:
            print(f"{r['size']:10} {r['engine']:20}  error: {r['error'][:60]}")
            continue
        f = r["fits"]
        print(f"{r['size']:10} {r['engine']:20} {r['prepare_ms']:7.2f} {r['interp_ms']:7.2f}   "
              + "  ".join("yes" if f[k] else " no" for k in (60, 90, 120)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
