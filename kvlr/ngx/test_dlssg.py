"""Check framegen.kvlr_dlssg.DlssFgInterpolator on a 60 fps clip played as a 30 fps game: every other frame is a real
frame, the ones between are generated (t = 0.5, 2x) and scored against the frame that was left out (PSNR), next to a
plain 50/50 blend. Saves one generated frame and its ground truth.

    python kvlr/ngx/test_dlssg.py CLIP.mp4 OUTDIR [--pairs 60] [--hz 60]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framegen.kvlr_dlssg import DlssFgInterpolator  # noqa: E402


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    m = np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2)
    return 99.0 if m == 0 else 10 * np.log10(255 ** 2 / m)


class S:
    hz = 60


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("outdir")
    ap.add_argument("--pairs", type=int, default=60)
    ap.add_argument("--hz", type=int, default=60)
    a = ap.parse_args()
    S.hz = a.hz
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(a.clip)
    frames = []
    while len(frames) < a.pairs * 2 + 1:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    h, w = frames[0].shape[:2]
    it = DlssFgInterpolator(w, h, S())
    gen_p, blend_p, slot, t0 = [], [], 0, time.perf_counter()
    for i in range(0, len(frames) - 2, 2):
        for j, real in enumerate((frames[i], frames[i + 2]) if i == 0 else (frames[i + 2],)):
            it.load(torch.from_numpy(real).cuda())
            it.prepare(slot)
            slot ^= 1
        g = it.interpolate(1 - slot, 0.5).cpu().numpy()
        truth = frames[i + 1]
        gen_p.append(psnr(g, truth))
        blend_p.append(psnr(((frames[i].astype(np.uint16) + frames[i + 2]) // 2).astype(np.uint8), truth))
        if i == 40:
            cv2.imwrite(str(out / "fg_generated.png"), g)
            cv2.imwrite(str(out / "fg_truth.png"), truth)
    ms = sorted(it.gpu_ms[3:])
    print(f"{len(gen_p)} generated frames {w}x{h}: PSNR vs the real left-out frame {np.median(gen_p):.2f} dB "
          f"(50/50 blend {np.median(blend_p):.2f} dB); DLSS-G GPU p50 {ms[len(ms) // 2]:.2f} ms; "
          f"wall {(time.perf_counter() - t0) / len(gen_p) * 1000:.1f} ms per pair")
    it.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
