"""KVLR edition: NVIDIA DLSS Super Resolution as the AI upscaler (setting "ai_upscaler"), next to RTX VSR.

The window's "RTX VSR" scaler slot (framegen/io.py) gets a KvlrUpscaler, which has RTX VSR's interface and picks the
engine on every frame from the setting, so the choice switches live: "vsr" uses upstream's RTX VSR (framegen/rtxvsr.py
make_vsr); "dlss" runs DLSS SR in kvlr_ngx.dll (kvlr/ngx/kvlr_ngx.cpp, Direct3D 12 + NVIDIA's NGX). Both write NVIDIA's
packed 10-bit RGB into the window's texture, so the window code is unchanged.

DLSS SR's frames go through buffers shared between Direct3D 12 and CUDA (no copies through the CPU); the helper waits
for the graphics card after each frame (about the DLSS time). Motion ("dlss_motion"): "flow" measures it between each
frame and the one before with the graphics card's optical flow hardware (NVIDIA Optical Flow, in kvlr_ngx.dll), so
DLSS can follow moving things instead of smearing them; "zero" treats the picture as still.

Where kvlr_ngx.dll and NVIDIA's nvngx_dlss.dll are looked for: KVLR_NGX_DIR, then <app>/ngx (installed), then
installer/build/ngx (a development checkout).
"""
from __future__ import annotations

import ctypes
import os
import tempfile
from pathlib import Path

import torch

from .glcuda import _cudart

ENGINES = {"vsr": "RTX VSR", "dlss": "DLSS SR"}
PRESETS = {"auto": 0, "k": 11, "l": 12, "m": 13}  # NGX render presets (transformer models)
_D2D, _H2D = 3, 1
_EXT_MEM_D3D12_RESOURCE, _EXT_MEM_DEDICATED = 5, 1


def ngx_dir() -> Path | None:
    here = Path(__file__).resolve().parent
    for d in (os.environ.get("KVLR_NGX_DIR"), here.parent / "ngx", here.parent / "installer" / "build" / "ngx"):
        if d and (Path(d) / "kvlr_ngx.dll").exists() and (Path(d) / "nvngx_dlss.dll").exists():
            return Path(d)
    return None


def dlss_reason() -> str | None:
    """None if DLSS SR can be tried here, otherwise why not."""
    if ngx_dir() is None:
        return "the DLSS files (kvlr_ngx.dll, nvngx_dlss.dll) aren't installed"
    return None


class _ExtMemDesc(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("handle", ctypes.c_void_p), ("name", ctypes.c_void_p),
                ("size", ctypes.c_ulonglong), ("flags", ctypes.c_uint), ("reserved", ctypes.c_uint * 16)]


class _ExtBufDesc(ctypes.Structure):
    _fields_ = [("offset", ctypes.c_ulonglong), ("size", ctypes.c_ulonglong), ("flags", ctypes.c_uint),
                ("reserved", ctypes.c_uint * 16)]


class _Ngx:
    """kvlr_ngx.dll, loaded once per process."""
    dll = None

    @classmethod
    def get(cls):
        if cls.dll is None:
            d = ngx_dir()
            if d is None:
                raise RuntimeError(dlss_reason())
            os.add_dll_directory(str(d))
            dll = ctypes.CDLL(str(d / "kvlr_ngx.dll"))
            dll.kvlr_ngx_error.restype = ctypes.c_char_p
            dll.kvlr_ngx_adapter.restype = ctypes.c_char_p
            dll.kvlr_sr_shared_create.argtypes = [ctypes.c_uint] * 4 + [ctypes.c_int] + [
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_uint)] * 2
            dll.kvlr_sr_shared_eval.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
            dll.kvlr_sr_shared_eval_mv.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
            dll.kvlr_sr_shared_mv.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_ulonglong),
                                              ctypes.POINTER(ctypes.c_uint)]
            u, ull = ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_ulonglong)
            dll.kvlr_of_create.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_void_p,
                                           ull, ull, u, ull, u, u, u]
            dll.kvlr_of_run.argtypes = [ctypes.c_int]
            if not dll.kvlr_ngx_init(ctypes.c_wchar_p(str(d)), ctypes.c_wchar_p(tempfile.gettempdir())):
                raise RuntimeError(f"DLSS couldn't start: {dll.kvlr_ngx_error().decode()}")
            cls.dll = dll
        return cls.dll


class DlssSr:
    """DLSS SR for src_w x src_h RGBA frames into a CUDA array (the window's R32UI texture) as packed RGB10A2.
    The same call as framegen.rtxvsr.VfxVsr. Remade when the output size changes."""
    out_format = "rgb10a2"
    private = False
    how = "through NVIDIA's DLSS SDK (kvlr_ngx)"

    GRID = 4  # one motion vector per 4x4 pixels (spread to every pixel for DLSS)

    def __init__(self, src_w: int, src_h: int, preset: str = "auto", motion: str = "flow") -> None:
        self.ngx = _Ngx.get()
        self.rt = rt = _cudart()
        p, s, i = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
        rt.cudaMemcpy2DAsync.argtypes = [p, s, p, s, s, s, i, p]
        rt.cudaMemcpy2DToArrayAsync.argtypes = [p, s, s, p, s, s, s, i, p]
        rt.cudaImportExternalMemory.argtypes = [ctypes.POINTER(p), ctypes.POINTER(_ExtMemDesc)]
        rt.cudaExternalMemoryGetMappedBuffer.argtypes = [ctypes.POINTER(p), p, ctypes.POINTER(_ExtBufDesc)]
        rt.cudaDestroyExternalMemory.argtypes = [p]
        torch.zeros(1, device="cuda")
        self.stream = torch.cuda.current_stream()
        self.w, self.h, self.preset, self.motion = src_w, src_h, preset, motion
        self._of = None  # (in pointers, in stride, out pointer, out stride, out w, out h) once made
        self._cur = 0
        self.of_ms: list[float] = []
        self.size = None
        self._mem: list = []
        self.gpu_ms: list[float] = []
        self._reset = 1

    def _cuda(self, err: int, what: str) -> None:
        if err:
            raise RuntimeError(f"DLSS SR: {what} failed (CUDA error {err})")

    def _import(self, handle, size: int):
        d = _ExtMemDesc(type=_EXT_MEM_D3D12_RESOURCE, handle=handle, size=size, flags=_EXT_MEM_DEDICATED)
        mem = ctypes.c_void_p()
        self._cuda(self.rt.cudaImportExternalMemory(ctypes.byref(mem), ctypes.byref(d)), "import shared memory")
        ptr = ctypes.c_void_p()
        b = _ExtBufDesc(offset=0, size=size)
        self._cuda(self.rt.cudaExternalMemoryGetMappedBuffer(ctypes.byref(ptr), mem, ctypes.byref(b)), "map shared memory")
        self._mem.append(mem)
        return ptr

    def _free(self) -> None:
        for m in self._mem:
            self.rt.cudaDestroyExternalMemory(m)
        self._mem = []

    def _make(self, out_w: int, out_h: int) -> None:
        torch.cuda.synchronize()
        self._free()
        ih, oh = ctypes.c_void_p(), ctypes.c_void_p()
        isz, osz = ctypes.c_ulonglong(), ctypes.c_ulonglong()
        ip, op = ctypes.c_uint(), ctypes.c_uint()
        if not self.ngx.kvlr_sr_shared_create(self.w, self.h, out_w, out_h, PRESETS.get(self.preset, 0),
                                              ctypes.byref(ih), ctypes.byref(isz), ctypes.byref(ip),
                                              ctypes.byref(oh), ctypes.byref(osz), ctypes.byref(op)):
            raise RuntimeError(f"DLSS SR: {self.ngx.kvlr_ngx_error().decode()}")
        self.inp, self.in_pitch = self._import(ih, isz.value), ip.value
        self.out, self.out_pitch = self._import(oh, osz.value), op.value
        self.size, self._reset = (out_w, out_h), 1
        self.mv = None
        if self.motion == "flow":
            try:
                self._make_flow()
            except RuntimeError as e:
                print(f"[display] DLSS SR: no optical flow ({e}); motion treated as still")
                self.motion = "zero"
        print(f"[display] DLSS SR {self.w}x{self.h} -> {out_w}x{out_h} on {self.ngx.kvlr_ngx_adapter().decode()}, "
              f"motion: {'optical flow' if self.motion == 'flow' else 'none (still)'}")

    def _make_flow(self) -> None:
        mh, msz, mp = ctypes.c_void_p(), ctypes.c_ulonglong(), ctypes.c_uint()
        if not self.ngx.kvlr_sr_shared_mv(ctypes.byref(mh), ctypes.byref(msz), ctypes.byref(mp)):
            raise RuntimeError(self.ngx.kvlr_ngx_error().decode())
        self.mv, self.mv_pitch = self._import(mh, msz.value), mp.value
        if self._of is None:
            i0, i1, o = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
            istr, ostr, ow, oh = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
            if not self.ngx.kvlr_of_create(self.w, self.h, self.GRID, 20, ctypes.c_void_p(self.stream.cuda_stream),
                                           ctypes.byref(i0), ctypes.byref(i1), ctypes.byref(istr), ctypes.byref(o),
                                           ctypes.byref(ostr), ctypes.byref(ow), ctypes.byref(oh)):
                raise RuntimeError(self.ngx.kvlr_ngx_error().decode())
            self._of = ((i0.value, i1.value), istr.value, o.value, ostr.value, ow.value, oh.value)
            self._flow = torch.empty((oh.value, ow.value, 2), dtype=torch.int16, device="cuda")
            self._gray = torch.empty((self.h, self.w), dtype=torch.uint8, device="cuda")
            self._mvfull = torch.empty((self.h, self.w, 2), dtype=torch.float16, device="cuda")

    def _motion(self, rgba: torch.Tensor, stream) -> bool:
        """Optical flow from this frame back to the previous one, into the shared motion-vector buffer. False on the
        first frame (nothing to compare with)."""
        (ins, istr, out, ostr, ow, oh) = self._of
        with torch.cuda.stream(self.stream):
            c = rgba[..., :3].to(torch.int32)
            torch.div(c[..., 0] * 77 + c[..., 1] * 150 + c[..., 2] * 29, 256, rounding_mode="floor", out=c[..., 0])
            self._gray.copy_(c[..., 0])
        self._cuda(self.rt.cudaMemcpy2DAsync(ctypes.c_void_p(ins[self._cur]), istr, ctypes.c_void_p(self._gray.data_ptr()),
                                             self.w, self.w, self.h, _D2D, stream), "copy to optical flow")
        first = self._reset == 1
        if not first:
            if not self.ngx.kvlr_of_run(self._cur):
                raise RuntimeError(f"optical flow: {self.ngx.kvlr_ngx_error().decode()}")
            self._cuda(self.rt.cudaMemcpy2DAsync(ctypes.c_void_p(self._flow.data_ptr()), ow * 4, ctypes.c_void_p(out),
                                                 ostr, ow * 4, oh, _D2D, stream), "copy optical flow")
            with torch.cuda.stream(self.stream):
                g = self.GRID
                mv = self._flow.float().mul_(1.0 / 32.0)  # S10.5 fixed point -> pixels
                mv = mv.repeat_interleave(g, 0).repeat_interleave(g, 1)[: self.h, : self.w]
                self._mvfull.copy_(mv)
            self._cuda(self.rt.cudaMemcpy2DAsync(self.mv, self.mv_pitch, ctypes.c_void_p(self._mvfull.data_ptr()),
                                                 self.w * 4, self.w * 4, self.h, _D2D, stream), "copy motion")
        self._cur ^= 1
        return not first

    def __call__(self, rgba: torch.Tensor, out_array: ctypes.c_void_p, out_w: int, out_h: int,
                 quality: int | None = None) -> None:
        if (out_w, out_h) != self.size:
            self._make(out_w, out_h)
        stream = ctypes.c_void_p(self.stream.cuda_stream)
        rgba = rgba.contiguous()
        self._cuda(self.rt.cudaMemcpy2DAsync(self.inp, self.in_pitch, ctypes.c_void_p(rgba.data_ptr()), self.w * 4,
                                             self.w * 4, self.h, _D2D, stream), "copy in")
        use_mv = self._motion(rgba, stream) if self.motion == "flow" and self._of is not None else False
        self.stream.synchronize()  # the helper runs on its own queue; sync both sides on the CPU
        ms = ctypes.c_float()
        if not self.ngx.kvlr_sr_shared_eval_mv(self._reset, 1 if use_mv else 0, ctypes.byref(ms)):
            raise RuntimeError(f"DLSS SR: {self.ngx.kvlr_ngx_error().decode()}")
        self._reset = 0
        self.gpu_ms.append(ms.value)
        self._cuda(self.rt.cudaMemcpy2DToArrayAsync(out_array, 0, 0, self.out, self.out_pitch, out_w * 4, out_h, _D2D,
                                                    stream), "copy out")

    def forget(self, array) -> None:
        """(Nothing is cached per output array.)"""

    def close(self) -> None:
        torch.cuda.synchronize()
        self._free()


class KvlrUpscaler:
    """The window's AI upscaler: RTX VSR or DLSS SR by the "ai_upscaler" setting, switched live. RTX VSR's interface."""
    out_format = "rgb10a2"

    def __init__(self, settings, src_w: int, src_h: int, quality: int, clean: bool = False) -> None:
        self.settings, self.args, self._quality = settings, (src_w, src_h, clean), int(quality)
        self.engines: dict = {}
        torch.zeros(1, device="cuda")
        self.stream = torch.cuda.current_stream()
        self._engine()  # make the chosen one now, so a failure shows when it's picked

    @property
    def name(self) -> str:
        e = getattr(self.settings, "ai_upscaler", "vsr")
        return e if e in ENGINES else "vsr"

    def _engine(self):
        name = self.name
        if name not in self.engines:
            w, h, clean = self.args
            with torch.cuda.stream(self.stream):
                if name == "dlss":
                    self.engines[name] = DlssSr(w, h, getattr(self.settings, "dlss_preset", "auto"),
                                                getattr(self.settings, "dlss_motion", "flow"))
                else:
                    from .rtxvsr import make_vsr
                    self.engines[name] = make_vsr(w, h, self._quality, clean=clean)
            e = self.engines[name]
            if e.out_format != self.out_format:
                raise RuntimeError(f"{ENGINES[name]} writes {e.out_format}, the window expects {self.out_format}")
        return self.engines[name]

    @property
    def how(self) -> str:
        return f"{ENGINES[self.name]} {self._engine().how}"

    @property
    def label(self) -> str:
        return "DLSS SR" if self.name == "dlss" else f"RTX VSR q{self.quality}"

    @property
    def private(self) -> bool:
        return getattr(self._engine(), "private", False)

    @property
    def gpu_ms(self) -> list:
        return self._engine().gpu_ms

    @property
    def quality(self) -> int:
        return self._quality

    @quality.setter
    def quality(self, value: int) -> None:
        self._quality = int(value)
        if "vsr" in self.engines:
            self.engines["vsr"].quality = value

    def __call__(self, rgba, out_array, out_w, out_h, quality=None) -> None:
        self._engine()(rgba, out_array, out_w, out_h, *(() if self.name == "dlss" else (quality,)))

    def forget(self, array) -> None:
        for e in self.engines.values():
            e.forget(array)

    def close(self) -> None:
        for e in self.engines.values():
            e.close()


def make_upscaler(settings, src_w: int, src_h: int, quality: int, clean: bool = False):
    """What the window's RTX VSR slot holds (hook in framegen/io.py _vsr_ready)."""
    return KvlrUpscaler(settings, src_w, src_h, quality, clean)
