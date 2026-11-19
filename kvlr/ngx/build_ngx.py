"""Builds kvlr_ngx.dll (kvlr/ngx/kvlr_ngx.cpp) with MSVC, against NVIDIA's DLSS SDK kept outside the repository.

    python kvlr/ngx/build_ngx.py [--sdk PATH]

The SDK (headers, nvsdk_ngx_d.lib, nvngx_dlss.dll / nvngx_dlssg.dll) is NVIDIA's, under the NVIDIA RTX SDKs licence,
so it never goes in this public repo: by default it's ..\\kvlr-ps5-framegen-inputs\\dlss-sdk (git clone of NVIDIA/DLSS,
sparse: include, lib/Windows_x86_64/rel, lib/Windows_x86_64/x64, doc, LICENSE.txt). Output: installer/build/ngx/
(kvlr_ngx.dll plus copies of NVIDIA's runtime DLLs, which the installer ships in object form as the licence allows).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDK_DEFAULT = ROOT.parent / "kvlr-ps5-framegen-inputs" / "dlss-sdk"
OUT = ROOT / "installer" / "build" / "ngx"


def vcvars() -> Path:
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    path = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                           "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                          capture_output=True, text=True).stdout.strip()
    if not path:
        sys.exit("MSVC (Visual Studio Build Tools with C++) isn't installed")
    return Path(path) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", type=Path, default=SDK_DEFAULT)
    a = ap.parse_args()
    inc, lib = a.sdk / "include", a.sdk / "lib" / "Windows_x86_64" / "x64" / "nvsdk_ngx_d.lib"
    if not (inc / "nvsdk_ngx.h").exists() or not lib.exists():
        sys.exit(f"NVIDIA DLSS SDK not found in {a.sdk}")
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).with_name("kvlr_ngx.cpp")
    nvof = ROOT.parent / "kvlr-ps5-framegen-inputs" / "nvof"  # NVIDIA Optical Flow SDK headers (BSD)
    if not (nvof / "nvOpticalFlowCuda.h").exists():
        sys.exit(f"NVIDIA Optical Flow SDK headers not found in {nvof}")
    cmd = (f'call "{vcvars()}" >nul && cl /nologo /O2 /MD /EHsc /std:c++17 /LD /I "{inc}" /I "{nvof}" /I "{Path(__file__).with_name('cuda_stub')}" "{src}" '
           f'/Fe:"{OUT / "kvlr_ngx.dll"}" /Fo:"{OUT}\\\\" /link "{lib}" d3d12.lib dxgi.lib advapi32.lib user32.lib')
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(r.stdout[-4000:], r.stderr[-2000:])
    if r.returncode:
        return r.returncode
    for dll in ("nvngx_dlss.dll", "nvngx_dlssg.dll"):
        shutil.copy2(a.sdk / "lib" / "Windows_x86_64" / "rel" / dll, OUT / dll)
    print(f"[ngx] built {OUT / 'kvlr_ngx.dll'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
