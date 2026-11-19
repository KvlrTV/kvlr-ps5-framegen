"""KVLR edition: depth estimated from the picture (Depth Anything V2 Small, Apache-2.0), for DLSS Frame Generation.

Captured video has no depth buffer, so DLSS FG can't tell a character in front of a background that slides behind
it; it then drags the background's motion into the character's outline. With "dlssg_depth" = "estimated", each real
frame goes through Depth Anything V2 Small (TensorRT, its fp16 model, at 700x392) and its relative depth (1 = near, 0 = far,
DLSS-G's "inverted" depth) is handed to DLSS FG with the motion vectors.

The model (onnx-community/depth-anything-v2-small, onnx/model_fp16.onnx, ~50 MB) is looked for at KVLR_DEPTH_MODEL, then
<app>/models/depth_anything_v2_small.onnx, then ..\\kvlr-ps5-framegen-inputs\\depth (a development checkout). The
TensorRT engine is built once per GPU / TensorRT version (a minute or so) and cached in models/trt, like RIFE's.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import torch
import torch.nn.functional as F

NAME = "depth_anything_v2_small_fp16.onnx"
IN_W, IN_H = 700, 392  # multiples of 14 (the model's patch size), about 16:9
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def model_path() -> Path | None:
    here = Path(__file__).resolve().parent
    for p in (os.environ.get("KVLR_DEPTH_MODEL"), here.parent / "models" / NAME,
              here.parent.parent / "kvlr-ps5-framegen-inputs" / "depth" / NAME):
        if p and Path(p).exists():
            return Path(p)
    return None


def depth_reason() -> str | None:
    if model_path() is None:
        return f"the depth model ({NAME}) isn't installed"
    try:
        from .trt import trt_available
        if not trt_available():
            return "TensorRT isn't available"
    except Exception as e:  # noqa: BLE001
        return f"TensorRT couldn't load: {str(e)[:120]}"
    return None


class DepthEstimator:
    """bgr (HxWx3 uint8 CUDA) -> HxW float32 depth in 0..1 (1 = near), on PyTorch's current stream."""

    def __init__(self, width: int, height: int, device: torch.device) -> None:
        from .trt import ENGINE_DIR, import_trt
        why = depth_reason()
        if why:
            raise RuntimeError(why)
        trt = import_trt()
        self.trt, self.w, self.h, self.device = trt, width, height, device
        self.logger = trt.Logger(trt.Logger.WARNING)
        src = model_path()
        gpu = torch.cuda.get_device_name(device)
        key = hashlib.sha1(f"{src.stat().st_size}|{IN_W}x{IN_H}|{gpu}|{trt.__version__}".encode()).hexdigest()[:12]
        ENGINE_DIR.mkdir(parents=True, exist_ok=True)
        engine = ENGINE_DIR / f"depth_v2s_{IN_W}x{IN_H}_{key}.engine"
        if not engine.exists():
            self._build(src, engine)
        self.engine = trt.Runtime(self.logger).deserialize_cuda_engine(engine.read_bytes())
        if self.engine is None:
            raise RuntimeError(f"could not load TensorRT engine {engine}")
        self.ctx = self.engine.create_execution_context()
        self.ctx.set_input_shape("pixel_values", (1, 3, IN_H, IN_W))
        self.inp = torch.empty((1, 3, IN_H, IN_W), dtype=torch.float32, device=device)
        self.out = torch.empty((1, IN_H, IN_W), dtype=torch.float32, device=device)
        self.ctx.set_tensor_address("pixel_values", self.inp.data_ptr())
        self.ctx.set_tensor_address("predicted_depth", self.out.data_ptr())
        self.mean, self.std = MEAN.to(device), STD.to(device)
        self.lo = self.hi = None  # smoothed range, so the scale doesn't jump frame to frame
        self.depth = torch.empty((height, width), dtype=torch.float32, device=device)

    def _build(self, src: Path, engine: Path) -> None:
        trt = self.trt
        print(f"[depth] building the depth engine {engine.name} (once, about a minute)...")
        t0 = time.perf_counter()
        builder = trt.Builder(self.logger)
        network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
        parser = trt.OnnxParser(network, self.logger)
        if not parser.parse_from_file(str(src)):
            raise RuntimeError("TensorRT could not parse the depth model: "
                               + "; ".join(str(parser.get_error(i)) for i in range(parser.num_errors)))
        config = builder.create_builder_config()
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 2 << 30)
        profile = builder.create_optimization_profile()
        shape = (1, 3, IN_H, IN_W)
        profile.set_shape("pixel_values", shape, shape, shape)
        config.add_optimization_profile(profile)
        blob = builder.build_serialized_network(network, config)
        if blob is None:
            raise RuntimeError("TensorRT depth engine build failed")
        engine.write_bytes(bytes(blob))
        print(f"[depth] built in {time.perf_counter() - t0:.0f} s")

    @torch.no_grad()
    def __call__(self, bgr: torch.Tensor) -> torch.Tensor:
        x = bgr.permute(2, 0, 1).unsqueeze(0).flip(1).float().div_(255.0)  # BGR -> RGB, 0..1
        x = F.interpolate(x, size=(IN_H, IN_W), mode="area")
        self.inp.copy_((x - self.mean) / self.std)
        if not self.ctx.execute_async_v3(torch.cuda.current_stream(self.device).cuda_stream):
            raise RuntimeError("TensorRT depth execution failed")
        d = self.out[0]  # relative inverse depth: bigger = nearer
        q = torch.quantile(d.flatten()[::16], torch.tensor([0.02, 0.98], device=d.device))
        lo, hi = q[0], q[1]
        if self.lo is None:
            self.lo, self.hi = lo.clone(), hi.clone()
        else:
            self.lo.lerp_(lo, 0.2)
            self.hi.lerp_(hi, 0.2)
        n = ((d - self.lo) / (self.hi - self.lo).clamp_min(1e-6)).clamp_(0.0, 1.0).mul_(0.95).add_(0.05)
        self.depth.copy_(F.interpolate(n[None, None], size=(self.h, self.w), mode="bilinear", align_corners=False)[0, 0])
        return self.depth
