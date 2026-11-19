"""KVLR edition: 4K capture cards with steady 60/90/120 fps frame generation (upstream's "capture_size" + setting "capture_work").

Upstream's "Capture card resolution" setting (since 0.3.7) asks the card for 1080p, 1440p or 4K. Frame generation then works at
the "work size": the captured size, or smaller when the AI model can't keep the frame rate there. The window and
OBS output upscale back to the screen's size as they do for Remote Play.

Why the work size: frame generation at 4K can't make AI frames fast enough for 90 or 120 fps yet. RIFE at 4K
(kvlr/bench_4k.py on an RTX 5070 Ti, TensorRT at half motion detail) takes 8.0 ms per real frame + 15.3 ms per AI
frame, against 3.0 + 6.6 ms at 1440p; and the whole pipeline (a 4K 60 Hz signal carrying a 30 fps game, a lossless
recording standing in for the card) keeps about 90% of the extra frames at 90 or 120 fps only when it works at
1080p. Handling a 4K frame (conversion, scaling, comparing) costs several ms on its own before any AI work.
Auto therefore: 90 and 120 fps work at 1080p; 60 fps works at the captured size with NVIDIA VFG at low or medium
quality and at 1440p (at most) otherwise. (NVIDIA's licence for VFG forbids publishing its results, so none are given
here; kvlr/bench_4k.py shows them on the PC.)

Hook (marked KVLR) in run.py: wrap() puts WorkSize() round the source once the settings are loaded.
"""
from __future__ import annotations


SIZES = {"2160": (3840, 2160), "1440": (2560, 1440), "1080": (1920, 1080)}


def work_size(settings, w: int, h: int) -> tuple[int, int]:
    """The size frame generation works at, for a w x h capture (aspect kept, even numbers)."""
    choice = str(getattr(settings, "capture_work", "auto"))
    if choice == "native":
        return w, h
    if choice in SIZES:
        cap = SIZES[choice]
    else:  # auto, from the measurements above
        model, hz = getattr(settings, "model", "4.22.lite"), int(getattr(settings, "hz", 60))
        quality = getattr(settings, "vfg_quality", "medium")
        if not getattr(settings, "interp", True):
            return w, h  # no AI frames: nothing to keep up with
        if hz > 60:
            cap = SIZES["1080"]  # 90 and 120 fps: measured, 1080p is the only work size that comes close today
        elif model == "vfg" and quality in ("low", "medium"):
            return w, h
        else:
            cap = SIZES["1440"]
    if w * h <= cap[0] * cap[1]:
        return w, h
    s = min(cap[0] / w, cap[1] / h)
    return max(2, round(w * s / 2) * 2), max(2, round(h * s / 2) * 2)


class WorkSize:
    """Wraps a capture source so its frames come out at the work size (GPU frames resized on the GPU, area filter).
    Everything else (info, sound, close, ...) is the source's own."""

    def __init__(self, src, w: int, h: int) -> None:
        self._src, self.w, self.h = src, w, h
        print(f"[capture] frame generation works at {w}x{h} (captured {src.w}x{src.h}); the window and OBS output "
              f"upscale to their size")

    def __getattr__(self, name):
        return getattr(self._src, name)

    def __iter__(self):
        for tick in self._src:
            frame = getattr(tick, "frame", None)
            if frame is not None:
                tick.frame = self._resize(frame)
            yield tick

    def _resize(self, frame):
        if hasattr(frame, "is_cuda"):
            import torch.nn.functional as F
            x = frame.permute(2, 0, 1).unsqueeze(0).float()
            x = F.interpolate(x, size=(self.h, self.w), mode="area")
            return x.round_().clamp_(0, 255).to(frame.dtype)[0].permute(1, 2, 0).contiguous()
        import cv2
        return cv2.resize(frame, (self.w, self.h), interpolation=cv2.INTER_AREA)


def wrap(src, settings, kind: str):
    """The capture source at its work size (unchanged for other sources, or when it's already small enough)."""
    if kind != "capture":
        return src
    w, h = work_size(settings, src.w, src.h)
    return src if (w, h) == (src.w, src.h) else WorkSize(src, w, h)
