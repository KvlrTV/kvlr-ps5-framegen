"""Stage-2 check: framegen.kvlr_dlss.DlssSr on a moving clip, through the CUDA <-> Direct3D 12 shared buffers, into a
CUDA array as the window's texture would get it. Saves frame N's 4K output (unpacked) and a bicubic one to compare.

    python kvlr/ngx/test_dlss_cuda.py CLIP.mp4 OUTDIR [--frames 120] [--save 100] [--preset auto]
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framegen.kvlr_dlss import DlssSr  # noqa: E402
from framegen.glcuda import _cudart  # noqa: E402


class ChannelDesc(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("z", ctypes.c_int), ("w", ctypes.c_int), ("f", ctypes.c_int)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("outdir")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--save", type=int, default=100)
    ap.add_argument("--preset", default="auto")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--motion", default="flow")
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(a.clip)
    ok, bgr = cap.read()
    h, w = bgr.shape[:2]
    ow, oh = int(w * a.scale), int(h * a.scale)
    rt = _cudart()
    arr = ctypes.c_void_p()
    desc = ChannelDesc(32, 0, 0, 0, 1)  # one 32-bit unsigned channel, as the window's R32UI texture
    rt.cudaMallocArray.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ChannelDesc), ctypes.c_size_t,
                                   ctypes.c_size_t, ctypes.c_uint]
    assert rt.cudaMallocArray(ctypes.byref(arr), ctypes.byref(desc), ow, oh, 0) == 0
    sr = DlssSr(w, h, a.preset, a.motion)
    n, t0 = 0, time.perf_counter()
    while ok and n < a.frames:
        rgba = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)).cuda()
        sr(rgba, arr, ow, oh)
        if n == a.save:
            words = torch.empty((oh, ow), dtype=torch.int32, device="cuda")
            rt.cudaMemcpy2DFromArray.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
                                                 ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int]
            assert rt.cudaMemcpy2DFromArray(ctypes.c_void_p(words.data_ptr()), ow * 4, arr, 0, 0, ow * 4, oh, 3) == 0
            v = words.cpu().numpy().astype(np.uint32)
            rgb = np.stack([(v >> s) & 1023 for s in (0, 10, 20)], -1).astype(np.float32) * 255 / 1023
            cv2.imwrite(str(out / f"dlss_{a.motion}.png"), cv2.cvtColor(rgb.round().astype(np.uint8), cv2.COLOR_RGB2BGR))
            cv2.imwrite(str(out / "bicubic.png"), cv2.resize(bgr, (ow, oh), interpolation=cv2.INTER_CUBIC))
            cv2.imwrite(str(out / "source.png"), bgr)
        n += 1
        ok, bgr = cap.read()
    torch.cuda.synchronize()
    wall = (time.perf_counter() - t0) / n * 1000
    g = sorted(sr.gpu_ms[5:])
    print(f"{n} frames {w}x{h} -> {ow}x{oh}: DLSS GPU p50 {g[len(g) // 2]:.2f} ms, p95 {g[int(len(g) * .95)]:.2f} ms; "
          f"whole call incl. decode+upload {wall:.1f} ms")
    sr.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
