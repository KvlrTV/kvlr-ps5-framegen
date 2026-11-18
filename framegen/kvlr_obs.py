"""KVLR edition: a clean feed for OBS through Spout (settings "obs_output", "obs_size", "obs_fps").

The game window (io.GLWindowSink) calls ObsFeed.frame() after it has drawn the picture and before it draws its menu,
stats and notes, so the feed never carries them. The picture goes to OBS as a GPU texture (Spout shares a Direct3D
11 texture through NVIDIA's GL/DX interop): no copy through the CPU.

- When the picture on screen is exactly the feed's size (fullscreen on a 4K monitor with a 4K feed), the feed is a
  1:1 copy of it, so OBS shows what the player sees, look and RTX VSR included.
- Otherwise the source frame is upscaled with an FSR 1 of the feed's own (sharing the window's would re-make its
  buffers every frame, the two sizes differing), without the look.
- At most obs_fps pictures a second: with 90 or 120 fps output, frames in between are skipped for OBS only.
- Off with HDR output (the window's frames are then PQ float, which OBS's Spout capture would show wrongly).

In OBS: install the Spout2 plugin for OBS, add a "Spout2 Capture" source and pick the sender "KVLR PS5".
FRAMEGEN_OBS_TEST=1 prints each send's size and timing (scripts don't need OBS: SpoutGL's receiver reads it back).
"""
from __future__ import annotations

import os
import time

from .kvlr_settings import OBS_SENDER, OBS_SIZES


class ObsFeed:
    def __init__(self, GL, sharpness: float) -> None:
        self.GL = GL
        self.sharpness = sharpness
        self.sender = None
        self.fsr = None
        self.target = None  # (texture, framebuffer, w, h)
        self.next_due = 0.0
        self.sent = 0
        self.failed = False  # Spout couldn't start: say so once, then stay off this session
        self.test = os.environ.get("FRAMEGEN_OBS_TEST") == "1"

    # ---- per frame (GL thread, the window's context current) ------------------------------------------------
    def frame(self, sink, target: int, x0: int, y0: int, dw: int, dh: int) -> None:
        st = sink.settings
        if not getattr(st, "obs_output", False) or sink.hdr10 or self.failed:
            if self.sender is not None:
                self._release()
            return
        period = 1.0 / float(st.obs_fps)
        now = time.perf_counter()
        if now < self.next_due - 0.25 * period:
            return  # a frame in between, for OBS only
        self.next_due = self.next_due + period if now - self.next_due < period else now + period
        if self.sender is None and not self._start():
            return
        w, h = OBS_SIZES.get(str(st.obs_size), OBS_SIZES["2160"])
        GL = self.GL
        vp = GL.glGetIntegerv(GL.GL_VIEWPORT)
        tex, fbo = self._target(w, h)
        if (dw, dh) == (w, h):  # what's on screen, 1:1
            GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, target)
            GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, fbo)
            GL.glBlitFramebuffer(x0, y0, x0 + dw, y0 + dh, 0, 0, w, h, GL.GL_COLOR_BUFFER_BIT, GL.GL_NEAREST)
            how = "copy"
        elif self._fsr() is not None:
            self.fsr.sharpness = st.fsr_sharpness
            self.fsr.draw(sink.tex, sink.w, sink.h, fbo, 0, 0, w, h)
            how = "fsr"
        else:  # no FSR: a filtered blit from the source frame (row 0 = image top, so flipped)
            GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, sink.fbo)
            GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, fbo)
            GL.glBlitFramebuffer(0, 0, sink.w, sink.h, 0, h, w, 0, GL.GL_COLOR_BUFFER_BIT, GL.GL_LINEAR)
            how = "bilinear"
        t0 = time.perf_counter()
        # GL's rows run bottom-up and Spout's (Direct3D's) top-down: invert.
        ok = self.sender.sendTexture(int(tex), GL.GL_TEXTURE_2D, w, h, True, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target)
        GL.glViewport(int(vp[0]), int(vp[1]), int(vp[2]), int(vp[3]))
        self.sent += 1
        if self.test:
            print(f"[obs] {self.sent}: {how} {w}x{h} send {1000 * (time.perf_counter() - t0):.2f} ms ok={ok}")
        if self.sent == 1:
            print(f"[obs] OBS output on: Spout sender \"{OBS_SENDER}\", {w}x{h} at up to {st.obs_fps} fps ({how})")

    # ---- set-up ---------------------------------------------------------------------------------------------
    def _start(self) -> bool:
        try:
            import SpoutGL
            self.sender = SpoutGL.SpoutSender()
            self.sender.setSenderName(OBS_SENDER)
            return True
        except Exception as e:  # noqa: BLE001 - OBS output is optional; the game carries on without it
            self.failed, self.sender = True, None
            print(f"[obs] OBS output unavailable ({str(e)[:200]}); it stays off this session")
            return False

    def _fsr(self):
        if self.fsr is None:
            try:
                from .fsr import FsrScaler
                self.fsr = FsrScaler(self.GL, self.sharpness)
            except Exception as e:  # noqa: BLE001
                print(f"[obs] FSR 1 unavailable for OBS output ({str(e)[:200]}); using bilinear")
                self.fsr = False
        return self.fsr or None

    def _target(self, w: int, h: int) -> tuple[int, int]:
        GL = self.GL
        if self.target is not None and self.target[2:] == (w, h):
            return self.target[:2]
        self._free_target()
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, tex, 0)
        self.target = (tex, fbo, w, h)
        return tex, fbo

    def _free_target(self) -> None:
        if self.target is not None:
            self.GL.glDeleteFramebuffers(1, [self.target[1]])
            self.GL.glDeleteTextures([self.target[0]])
            self.target = None

    def _release(self) -> None:
        try:
            self.sender.releaseSender()
        except Exception:  # noqa: BLE001
            pass
        self.sender = None
        print(f"[obs] OBS output off ({self.sent} pictures sent)")

    def close(self) -> None:
        if self.sender is not None:
            self._release()
        self._free_target()
        if self.fsr:
            self.fsr.close()
        self.fsr = None
