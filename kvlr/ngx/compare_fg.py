"""Compare DLSS FG motion variants with NVIDIA VFG on a real capture (60 Hz recording of a 30 fps game).

    python kvlr/ngx/compare_fg.py CLIP.mkv OUTDIR [--crop x,y,w,h] [--pairs 6]

Finds the game's real frames (a new picture, not a repeat), picks the pairs with the most motion, and for each makes
the in-between frame (t = 0.5) with every variant. Writes OUTDIR/compare_N.jpg: per pair, the previous real frame, then
each variant's generated frame, cropped (by default round the screen's centre, where a third-person character is).
NVIDIA VFG needs FRAMEGEN_VFX_PATH (its results stay on this PC: NVIDIA's licence).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framegen.kvlr_dlssg import DlssFgInterpolator  # noqa: E402

VARIANTS = [  # label, kwargs (None: NVIDIA VFG)
    ("NVIDIA VFG (reference)", None),
    ("DLSS FG now: 4x4 fast", dict(grid=4, perf=20, motion="flow")),
    ("2x2 medium", dict(grid=2, perf=10, motion="flow")),
    ("1x1 slow", dict(grid=1, perf=5, motion="flow")),
    ("4x4 slow + median", dict(grid=4, perf=5, motion="median")),
    ("no motion", dict(grid=4, perf=20, motion="zero")),
]


class S:
    hz = 60


def real_frames(path: str, limit: int = 600) -> list[np.ndarray]:
    cap, out, prev = cv2.VideoCapture(path), [], None
    while len(out) < limit:
        ok, f = cap.read()
        if not ok:
            break
        if prev is None or np.mean(np.abs(f.astype(np.int16) - prev)) > 0.6:
            out.append(f)
        prev = f.astype(np.int16)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("outdir")
    ap.add_argument("--crop", default="660,240,600,600")
    ap.add_argument("--pairs", type=int, default=6)
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    frames = real_frames(a.clip)
    print(f"{len(frames)} real frames")
    motion = [np.mean(np.abs(frames[i + 1].astype(np.int16) - frames[i])) for i in range(len(frames) - 1)]
    order = sorted(range(4, len(frames) - 1), key=lambda i: -motion[i])
    picks = sorted(order[: a.pairs * 4: 4])[: a.pairs]  # spread out among the most moving pairs
    x, y, w, h = map(int, a.crop.split(","))
    results: dict[int, list[np.ndarray]] = {i: [] for i in picks}
    for label, kw in VARIANTS:
        H, W = frames[0].shape[:2]
        if kw is None:
            if not os.environ.get("FRAMEGEN_VFX_PATH"):
                print("skipping NVIDIA VFG: FRAMEGEN_VFX_PATH not set"); continue
            from framegen.vfg import VfgInterpolator
            it = VfgInterpolator(W, H, "medium")
        else:
            it = DlssFgInterpolator(W, H, S(), **kw)
        slot = 0
        for i in range(0, max(picks) + 1):
            it.load(torch.from_numpy(frames[i]).cuda())
            it.prepare(slot)
            slot ^= 1
            if i in [p + 1 for p in picks]:
                g = it.interpolate(1 - slot, 0.5).cpu().numpy()
                results[i - 1].append(cv2.putText(g[y:y + h, x:x + w].copy(), label, (8, 26),
                                                  cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2))
        if hasattr(it, "close"):
            it.close()
        del it
        torch.cuda.empty_cache()
        print("done", label)
    for n, i in enumerate(picks):
        prev = cv2.putText(frames[i][y:y + h, x:x + w].copy(), "real frame before", (8, 26),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        tiles = [prev] + results[i]
        while len(tiles) % 4:
            tiles.append(np.zeros_like(prev))
        rows = [np.hstack(tiles[k:k + 4]) for k in range(0, len(tiles), 4)]
        cv2.imwrite(str(out / f"compare_{n}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"wrote {len(picks)} comparisons to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
