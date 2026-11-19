"""KVLR edition: NVIDIA DLSS Frame Generation (DLSS-G, multi-frame on RTX 50) as the AI engine, next to NVIDIA VFG.

The AI engine setting ("model") gets a third choice, "dlssg" (NVIDIA DLSS FG), next to RIFE and NVIDIA VFG; it uses
DlssFgInterpolator below, which has VFG's interface (load / prepare / interpolate at fraction t). It runs in
kvlr_ngx.dll (kvlr/ngx/kvlr_ngx.cpp): each real frame goes to DLSS-G with motion vectors measured by the graphics
card's optical flow hardware (pixels from this frame back to the previous one), a constant depth and identity camera
matrices, since captured video has no game data. DLSS-G makes `count` evenly spaced frames per pair (1 for 60 fps
from a 30 fps game, 2 for 90, 3 for 120), so a requested fraction t is taken to the nearest of them.

Hooks (marked KVLR): framegen/settings.py (the choice), run.py (session_config, build, fallback to RIFE, labels).
Steady HUD (framegen/steady.py) works as with VFG: the HUD's real pixels are put back over each generated frame.
Measured on a known 16 px pan: generated frames match the true in-between positions to 68.5 dB (a plain blend: 27-29
dB), at 2x and at 4x.
"""
from __future__ import annotations

import ctypes

import torch

from .kvlr_dlss import _D2D, DlssSr, _Ngx

COUNT = {60: 1, 90: 2, 120: 3}  # generated frames per real pair, by output rate (a 30 fps game)
FLOW_ID = 1  # this one's optical flow instance in kvlr_ngx.dll (DLSS SR's is 0)


class DlssFgInterpolator:
    """DLSS Frame Generation behind RifeInterpolator's / VfgInterpolator's interface (HxWx3 BGR uint8 frames)."""

    def __init__(self, width: int, height: int, settings=None, device: str = "cuda") -> None:
        self.w, self.h, self.settings = width, height, settings
        self.device = torch.device(device)
        self.version, self.scale, self.trt = "DLSS FG", 1.0, None
        self.private, self.hdr, self.frame_dtype = False, False, torch.uint8
        self.ngx = n = _Ngx.get()
        p, ull, u = ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_uint)
        n.kvlr_fg_create.argtypes = [ctypes.c_uint, ctypes.c_uint, p, ull, p, ull, p, ull, u]
        n.kvlr_fg_eval.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
        n.kvlr_of_create2.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int,
                                      ctypes.c_void_p, ull, ull, u, ull, u, u, u]
        n.kvlr_of_run2.argtypes = [ctypes.c_int, ctypes.c_int]
        torch.zeros(1, device=self.device)
        self.stream = torch.cuda.current_stream(self.device)
        # shared buffers (the DlssSr helpers do the CUDA import)
        self._io = DlssSr.__new__(DlssSr)
        self._io.rt, self._io._mem, self._io.ngx = None, [], n
        from .glcuda import _cudart
        self.rt = rt = _cudart()
        self._io.rt = rt
        pp, s, i = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
        rt.cudaMemcpy2DAsync.argtypes = [pp, s, pp, s, s, s, i, pp]
        from .kvlr_dlss import _ExtBufDesc, _ExtMemDesc
        rt.cudaImportExternalMemory.argtypes = [ctypes.POINTER(pp), ctypes.POINTER(_ExtMemDesc)]
        rt.cudaExternalMemoryGetMappedBuffer.argtypes = [ctypes.POINTER(pp), pp, ctypes.POINTER(_ExtBufDesc)]
        rt.cudaDestroyExternalMemory.argtypes = [pp]
        ih, mh, oh = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        isz, msz, osz, pitch = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_uint()
        if not n.kvlr_fg_create(width, height, ctypes.byref(ih), ctypes.byref(isz), ctypes.byref(mh), ctypes.byref(msz),
                                ctypes.byref(oh), ctypes.byref(osz), ctypes.byref(pitch)):
            raise RuntimeError(f"DLSS Frame Generation: {n.kvlr_ngx_error().decode()}")
        self.pitch = pitch.value
        self.buf_in = self._io._import(ih, isz.value)
        self.buf_mv = self._io._import(mh, msz.value)
        self.buf_out = self._io._import(oh, osz.value)
        # optical flow (one vector per 4x4 pixels)
        i0, i1, o = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        istr, ostr, ow, ohh = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        if not n.kvlr_of_create2(FLOW_ID, width, height, 4, 20, ctypes.c_void_p(self.stream.cuda_stream),
                                 ctypes.byref(i0), ctypes.byref(i1), ctypes.byref(istr), ctypes.byref(o),
                                 ctypes.byref(ostr), ctypes.byref(ow), ctypes.byref(ohh)):
            raise RuntimeError(f"DLSS Frame Generation: optical flow: {n.kvlr_ngx_error().decode()}")
        self.of_in, self.of_istr, self.of_out, self.of_ostr = (i0.value, i1.value), istr.value, o.value, ostr.value
        self.of_w, self.of_h = ow.value, ohh.value
        dev = self.device
        self.inp = torch.zeros((height, width, 3), dtype=torch.uint8, device=dev)
        self.in_u8 = self.inp
        self.out_u8 = torch.zeros((height, width, 3), dtype=torch.uint8, device=dev)
        self._rgba = torch.empty((height, width, 4), dtype=torch.uint8, device=dev)
        self._rgba[..., 3] = 255
        self._gen = torch.empty((height, width, 4), dtype=torch.uint8, device=dev)
        self._gray = torch.empty((height, width), dtype=torch.uint8, device=dev)
        self._flow = torch.empty((self.of_h, self.of_w, 2), dtype=torch.int16, device=dev)
        self._mv = torch.empty((height, width, 2), dtype=torch.float16, device=dev)
        self._new, self._frames, self.steady = False, 0, 0.0
        self.hud, self.real, self._steady_frames = None, None, 0
        self.gpu_ms: list[float] = []
        print(f"[dlssg] DLSS Frame Generation {width}x{height} on {n.kvlr_ngx_adapter().decode()} "
              f"(multi-frame: {'yes' if n.kvlr_ngx_fg_support() > 1 else 'no'})")

    def _check(self, err: int, what: str) -> None:
        if err:
            raise RuntimeError(f"DLSS Frame Generation: {what} failed (CUDA error {err})")

    def load(self, frame_u8: torch.Tensor) -> None:
        self.inp.copy_(frame_u8, non_blocking=True)

    @torch.no_grad()
    def prepare(self, slot: int) -> None:
        """A new real frame (in self.inp) into DLSS-G's frame buffer, with motion back to the previous real frame."""
        stream = ctypes.c_void_p(self.stream.cuda_stream)
        self._rgba[..., :3].copy_(self.inp.flip(-1))  # BGR -> RGB
        c = self.inp.to(torch.int32)
        self._gray.copy_(torch.div(c[..., 2] * 77 + c[..., 1] * 150 + c[..., 0] * 29, 256, rounding_mode="floor"))
        self._check(self.rt.cudaMemcpy2DAsync(ctypes.c_void_p(self.of_in[slot & 1]), self.of_istr,
                                              ctypes.c_void_p(self._gray.data_ptr()), self.w, self.w, self.h, _D2D,
                                              stream), "copy to optical flow")
        if self._frames > 0:
            if not self.ngx.kvlr_of_run2(FLOW_ID, slot & 1):
                raise RuntimeError(f"DLSS Frame Generation: {self.ngx.kvlr_ngx_error().decode()}")
            self._check(self.rt.cudaMemcpy2DAsync(ctypes.c_void_p(self._flow.data_ptr()), self.of_w * 4,
                                                  ctypes.c_void_p(self.of_out), self.of_ostr, self.of_w * 4, self.of_h,
                                                  _D2D, stream), "copy optical flow")
            mv = self._flow.float().mul_(1.0 / 32.0).repeat_interleave(4, 0).repeat_interleave(4, 1)
            self._mv.copy_(mv[: self.h, : self.w])
        else:
            self._mv.zero_()
        self._check(self.rt.cudaMemcpy2DAsync(self.buf_mv, self.pitch, ctypes.c_void_p(self._mv.data_ptr()), self.w * 4,
                                              self.w * 4, self.h, _D2D, stream), "copy motion")
        self._check(self.rt.cudaMemcpy2DAsync(self.buf_in, self.pitch, ctypes.c_void_p(self._rgba.data_ptr()),
                                              self.w * 4, self.w * 4, self.h, _D2D, stream), "copy frame")
        self._frames += 1
        self._new = True
        if self.steady > 0:
            from .vfg import _rgb
            self.real[slot].copy_(_rgb(self.inp, False))
            if self._steady_frames > 0:
                self.hud.mask(1 - slot, slot, self.real[1 - slot], self.real[slot])
            self._steady_frames += 1

    def count(self) -> int:
        hz = int(getattr(self.settings, "hz", 60)) if self.settings is not None else 60
        n = COUNT.get(hz, 1)
        return min(n, 3 if self.ngx.kvlr_ngx_fg_support() > 1 else 1)

    @torch.no_grad()
    def interpolate(self, newest_slot: int, t: float = 0.5) -> torch.Tensor:
        n = self.count()
        k = min(n, max(1, round(t * (n + 1))))
        self.stream.synchronize()  # DLSS-G reads the shared buffers on its own queue
        ms = ctypes.c_float()
        if not self.ngx.kvlr_fg_eval(1 if self._new else 0, n, k, 1 if self._frames < 2 else 0, ctypes.byref(ms)):
            raise RuntimeError(f"DLSS Frame Generation: {self.ngx.kvlr_ngx_error().decode()}")
        self._new = False
        self.gpu_ms.append(ms.value)
        stream = ctypes.c_void_p(self.stream.cuda_stream)
        self._check(self.rt.cudaMemcpy2DAsync(ctypes.c_void_p(self._gen.data_ptr()), self.w * 4, self.buf_out,
                                              self.pitch, self.w * 4, self.h, _D2D, stream), "copy generated frame")
        self.out_u8.copy_(self._gen[..., :3].flip(-1))  # RGB -> BGR
        if self.steady > 0 and self._steady_frames >= 2:  # Steady HUD: the real pixels where the HUD is
            from .vfg import _rgb, _store
            self.hud.t_now.fill_(t)
            _store(self.hud.blend(_rgb(self.out_u8, False), self.real[1 - newest_slot], self.real[newest_slot]),
                   self.out_u8)
        return self.out_u8

    def set_steady(self, threshold: float) -> None:
        """Steady HUD on (threshold: largest real-frame difference, 0..1, that counts as still) or off (0). Turned on
        mid-pair, it starts with the next two real frames."""
        if threshold > 0:
            if self.hud is None:
                from .steady import SteadyHud
                self.hud = SteadyHud(self.h, self.w, self.device)
                self.real = [torch.zeros((1, 3, self.h, self.w), dtype=torch.half, device=self.device) for _ in range(2)]
            self.hud.still_thr.fill_(threshold)
            if self.steady <= 0:
                self._steady_frames = 0
        self.steady = threshold

    def close(self) -> None:
        torch.cuda.synchronize()
        self._io._free()
