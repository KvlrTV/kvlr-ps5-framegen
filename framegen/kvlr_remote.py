"""KVLR edition: the clean picture for KVLR Remote Play (KVLR Bridge's remote_play service), through shared memory.

The bridge streams the picture to a browser. It creates a named shared memory, "Local\\kvlr-remote-frames"; while that
exists, the game window copies each finished frame (the picture as on screen, before any stats, menu or message) into
it, scaled to the size the bridge asked for. Nothing happens while the bridge isn't watching: one OpenFileMapping
call a second finds out.

Why not Spout (the OBS output)? A Spout receiver in another process gets at most ~12 pictures a second from this
window (each receive waits out Spout's 67 ms texture lock), and Windows' own capture (Desktop Duplication, Windows
Graphics Capture) gets no pictures from it at all. Both were measured on KvlrPC-NEW, 22 November 2026.

How: a blit to an FBO at the asked size (rows flipped, so row 0 is the top), then glReadPixels into one of two pixel
buffer objects. The read finishes on the GPU while the next frame is drawn; the frame after, the older buffer is
mapped and copied into the shared memory. So a frame reaches the bridge one frame late (16.7 ms at 60 Hz) and the
window never waits for the copy.

Shared memory layout (little-endian), written by this module and read by kvlr_bridge/services/remote_play.py:
    0  u32 magic 'KVRF'   4 u32 version 1    8 u32 width (bridge)   12 u32 height (bridge)
    16 u64 seq (this module: frames written; odd while a write is in progress)
    24 f64 time (perf counter of the window when the frame was drawn, seconds)
    32 u32 fourcc 'BGRA'  36..63 reserved
    64 width*height*4 bytes of BGRA, top row first
"""
from __future__ import annotations

import ctypes
import struct
import time

NAME = "Local\\kvlr-remote-frames"
HEADER = 64
MAGIC = 0x4652564B  # 'KVRF'
FILE_MAP_ALL_ACCESS = 0xF001F


class RemoteFeed:
    def __init__(self, GL) -> None:
        self.GL = GL
        self.k32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
        if self.k32 is not None:
            self.k32.OpenFileMappingW.restype = ctypes.c_void_p
            self.k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
            self.k32.MapViewOfFile.restype = ctypes.c_void_p
            self.k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                               ctypes.c_size_t]
            self.k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            self.k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = None
        self.view = None
        self.size = (0, 0)
        self.next_look = 0.0
        self.fbo = None  # (tex, fbo, w, h)
        self.pbos = None
        self.turn = 0
        self.pending = [None, None]  # draw time of the frame read into each PBO, or None
        self.seq = 0
        self.failed = False

    # ---- per frame (GL thread, the window's context current) ------------------------------------------------
    def frame(self, sink, target: int, x0: int, y0: int, dw: int, dh: int) -> None:
        if self.failed or self.k32 is None:
            return
        now = time.perf_counter()
        if self.view is None:
            if now < self.next_look:
                return
            self.next_look = now + 1.0
            if not self._open():
                return
        elif now >= self.next_look:  # the bridge stopped watching: its memory goes when it closes it
            self.next_look = now + 1.0
            if not self._still_wanted():
                self._close()
                return
        try:
            self._copy(target, x0, y0, dw, dh, now)
        except Exception as e:  # noqa: BLE001 - optional: the game carries on without it
            self.failed = True
            print(f"[remote] remote play output stopped ({str(e)[:200]})")
            self._close()

    def _copy(self, target, x0, y0, dw, dh, now) -> None:
        GL = self.GL
        w, h = self.size
        tex, fbo = self._targets(w, h)
        vp = GL.glGetIntegerv(GL.GL_VIEWPORT)
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, target)
        GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, fbo)
        # GL row 0 is the bottom: flip, so the buffer read back has the picture's top row first.
        GL.glBlitFramebuffer(x0, y0, x0 + dw, y0 + dh, 0, h, w, 0, GL.GL_COLOR_BUFFER_BIT, GL.GL_LINEAR)
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, fbo)
        i = self.turn
        GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, self.pbos[i])
        GL.glReadPixels(0, 0, w, h, GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, ctypes.c_void_p(0))
        self.pending[i] = now
        # The other buffer was read last frame: its pixels are ready by now.
        j = 1 - i
        if self.pending[j] is not None:
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, self.pbos[j])
            ptr = GL.glMapBuffer(GL.GL_PIXEL_PACK_BUFFER, GL.GL_READ_ONLY)
            if ptr:
                base = self.view
                self.seq += 1
                ctypes.memmove(base + 16, struct.pack("<Q", self.seq * 2 - 1), 8)  # odd: writing
                ctypes.memmove(base + HEADER, ptr, w * h * 4)
                ctypes.memmove(base + 24, struct.pack("<d", self.pending[j]), 8)
                ctypes.memmove(base + 16, struct.pack("<Q", self.seq * 2), 8)  # even: done
                GL.glUnmapBuffer(GL.GL_PIXEL_PACK_BUFFER)
            self.pending[j] = None
        GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target)
        GL.glViewport(int(vp[0]), int(vp[1]), int(vp[2]), int(vp[3]))
        self.turn = j

    # ---- the shared memory (made by the bridge) ----------------------------------------------------------------
    def _open(self) -> bool:
        h = self.k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, 0, NAME)
        if not h:
            return False
        view = self.k32.MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, 0)
        if not view:
            self.k32.CloseHandle(h)
            return False
        magic, _ver, w, hh = struct.unpack("<4I", ctypes.string_at(view, 16))
        if magic != MAGIC or not (16 <= w <= 3840 and 16 <= hh <= 2160):
            self.k32.UnmapViewOfFile(view)
            self.k32.CloseHandle(h)
            return False
        self.handle, self.view, self.size = h, view, (w, hh)
        ctypes.memmove(view + 32, b"BGRA", 4)
        print(f"[remote] KVLR Remote Play is watching: sending the picture at {w}x{hh}")
        return True

    def _still_wanted(self) -> bool:
        # The bridge clears the magic when it stops; a mapping we hold open would otherwise live on.
        return struct.unpack("<I", ctypes.string_at(self.view, 4))[0] == MAGIC

    def _targets(self, w: int, h: int):
        GL = self.GL
        if self.fbo is not None and self.fbo[2:] == (w, h):
            return self.fbo[:2]
        self._free_gl()
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, tex, 0)
        pbos = GL.glGenBuffers(2)
        for p in pbos:
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, p)
            GL.glBufferData(GL.GL_PIXEL_PACK_BUFFER, w * h * 4, None, GL.GL_STREAM_READ)
        GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
        self.fbo, self.pbos, self.pending, self.turn = (tex, fbo, w, h), list(pbos), [None, None], 0
        return tex, fbo

    def _free_gl(self) -> None:
        GL = self.GL
        if self.fbo is not None:
            GL.glDeleteFramebuffers(1, [self.fbo[1]])
            GL.glDeleteTextures([self.fbo[0]])
            self.fbo = None
        if self.pbos:
            GL.glDeleteBuffers(2, self.pbos)
            self.pbos = None

    def _close(self) -> None:
        if self.view:
            self.k32.UnmapViewOfFile(self.view)
        if self.handle:
            self.k32.CloseHandle(self.handle)
        if self.view:
            print(f"[remote] KVLR Remote Play stopped watching ({self.seq} pictures sent)")
        self.view = self.handle = None
        self.seq = 0

    def close(self) -> None:
        self._close()
        try:
            self._free_gl()
        except Exception:  # noqa: BLE001
            pass
