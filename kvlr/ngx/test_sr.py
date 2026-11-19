"""Stage-1 check of kvlr_ngx.dll: DLSS Super Resolution on one captured frame (fed a few times, as a still picture).

    python kvlr/ngx/test_sr.py IN.png OUT.png [--scale 2] [--preset 13] [--frames 8]

Prints the DLSS time per frame on the graphics card. Uses the build in installer/build/ngx.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

NGX = Path(__file__).resolve().parents[2] / "installer" / "build" / "ngx"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--preset", type=int, default=13, help="NGX render preset: 0 default, 11 K, 12 L, 13 M")
    ap.add_argument("--frames", type=int, default=8)
    a = ap.parse_args()
    os.add_dll_directory(str(NGX))
    dll = ctypes.CDLL(str(NGX / "kvlr_ngx.dll"))
    dll.kvlr_ngx_error.restype = ctypes.c_char_p
    dll.kvlr_ngx_adapter.restype = ctypes.c_char_p
    if not dll.kvlr_ngx_init(ctypes.c_wchar_p(str(NGX)), ctypes.c_wchar_p(tempfile.gettempdir())):
        print("init failed:", dll.kvlr_ngx_error().decode()); return 1
    print("adapter:", dll.kvlr_ngx_adapter().decode(), "| frame generation support:", dll.kvlr_ngx_fg_support())
    bgr = cv2.imread(a.inp)
    h, w = bgr.shape[:2]
    ow, oh = int(round(w * a.scale / 2) * 2), int(round(h * a.scale / 2) * 2)
    if not dll.kvlr_sr_create(w, h, ow, oh, a.preset):
        print("create failed:", dll.kvlr_ngx_error().decode()); return 1
    rgba = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA))
    out = np.empty((oh, ow, 4), np.uint8)
    ms = ctypes.c_float()
    times = []
    for i in range(a.frames):
        if not dll.kvlr_sr_upscale(rgba.ctypes.data_as(ctypes.c_void_p), out.ctypes.data_as(ctypes.c_void_p),
                                   1 if i == 0 else 0, ctypes.byref(ms)):
            print("upscale failed:", dll.kvlr_ngx_error().decode()); return 1
        times.append(ms.value)
    print(f"{w}x{h} -> {ow}x{oh}, preset {a.preset}: DLSS {sorted(times[2:])[len(times[2:]) // 2]:.2f} ms per frame "
          f"(first {times[0]:.2f})")
    cv2.imwrite(a.out, cv2.cvtColor(out, cv2.COLOR_RGBA2BGR))
    dll.kvlr_ngx_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
