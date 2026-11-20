"""KVLR edition: "Clean-up" (setting "cleanup"): removes compression blocks, ringing and mosquito noise from each real
frame, before frame generation and upscaling, so the AI frames are drawn from clean frames and FSR 1 / DLSS / VSR
don't enlarge and sharpen the blocks.

It is RTX VSR's Denoise mode (same size in and out) from NVIDIA's own `nvidia-vfx` package, the one NVIDIA VFG
comes in (framegen/vfg_setup.py): nothing of NVIDIA's ships with the app. NVIDIA's licence forbids publishing
benchmark results, so like framegen/rtxvsr.py VfxVsr its timings are never logged.

Repeats of a frame (a 30 fps game on a 60 Hz signal: A A B B) reuse the cleaned copy, so the pipeline still sees
them as repeats and the work is done once per real frame.
Hook (marked KVLR): framegen/kvlr_capture.py wrap(), so every source (capture card, Remote Play, window) gets it.
"""
from __future__ import annotations

LEVELS = {"light": 8, "medium": 9, "strong": 10, "max": 11}  # nvvfx QualityLevel DENOISE_LOW .. DENOISE_ULTRA


def reason() -> str | None:
    """Why Clean-up can't run here, or None."""
    try:
        from .rtxvsr import vfx_reason
        return vfx_reason()
    except Exception as e:  # noqa: BLE001
        return str(e)[:160]


class Denoise:
    """BGR uint8 frames (H x W x 3, CUDA or NumPy) in, the same out, cleaned."""

    def __init__(self, w: int, h: int, level: str = "medium") -> None:
        import torch
        from .vfg import import_vfx
        nvvfx = import_vfx()
        torch.zeros(1, device="cuda")
        self.w, self.h = w, h
        self.stream = torch.cuda.current_stream()
        self.fx = nvvfx.VideoSuperRes(quality=LEVELS.get(level, LEVELS["medium"]),
                                      device=torch.cuda.current_device(),
                                      image_encoding=nvvfx.ImageEncoding.RGB8)
        self.fx.output_width, self.fx.output_height = w, h
        self.fx.load()
        self.inp = torch.empty((3, h, w), dtype=torch.float32, device="cuda")
        self._last_in = None
        self._last_out = None

    def __call__(self, frame):
        import torch
        cpu = not hasattr(frame, "is_cuda")
        x = torch.from_numpy(frame).cuda(non_blocking=True) if cpu else frame
        if self._last_in is not None and x.shape == self._last_in.shape and torch.equal(x, self._last_in):
            out = self._last_out  # a repeat: the same cleaned frame, so it still reads as a repeat
        else:
            with torch.cuda.stream(self.stream):
                self.inp.copy_(x.flip(2).permute(2, 0, 1)).div_(255.0)  # BGR HWC -> RGB CHW, 0..1
            # Blocking: with non_blocking=True the result could be read before NVIDIA had written it (a frame late)
            res = self.fx.run(self.inp, non_blocking=False, stream_ptr=self.stream.cuda_stream)
            y = torch.from_dlpack(res.image)  # NVIDIA's memory until the next run: converted (copied) now
            out = y.mul(255.0).round_().clamp_(0, 255).to(torch.uint8).permute(1, 2, 0).flip(2).contiguous()
            self._last_in, self._last_out = x.clone(), out
        return out.cpu().numpy() if cpu else out

    def close(self) -> None:
        import torch
        torch.cuda.synchronize()
        self.fx.close()


class Cleaned:
    """Wraps a source so each frame goes through Denoise. Everything else is the source's own."""

    def __init__(self, src, level: str) -> None:
        self._src, self._level, self._fx = src, level, None
        print(f"[clean] Clean-up {level}: NVIDIA RTX Video denoise on each real frame, before frame generation")

    def __getattr__(self, name):
        return getattr(self._src, name)

    def __iter__(self):
        for tick in self._src:
            frame = getattr(tick, "frame", None)
            if frame is not None and self._fx is not False and str(frame.dtype).endswith("uint8"):  # not HDR halves
                try:
                    h, w = frame.shape[:2]
                    if self._fx is not None and (w, h) != (self._fx.w, self._fx.h):
                        self._fx.close()
                        self._fx = None
                    if self._fx is None:
                        self._fx = Denoise(w, h, self._level)
                    tick.frame = self._fx(frame)
                except Exception as e:  # noqa: BLE001 - an extra: play goes on without it
                    print(f"[clean] Clean-up stopped ({str(e)[:160]}); going on without it")
                    self._fx = False
            yield tick

    def close(self):
        if self._fx:
            try:
                self._fx.close()
            except Exception:  # noqa: BLE001
                pass
        return self._src.close()


def wrap(src, settings):
    level = str(getattr(settings, "cleanup", "off"))
    if level == "off" or level not in LEVELS:
        return src
    why = reason()
    if why:
        print(f"[clean] Clean-up unavailable: {why}")
        return src
    return Cleaned(src, level)
