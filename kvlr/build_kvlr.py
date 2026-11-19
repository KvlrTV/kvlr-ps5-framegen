r"""Builds the KVLR edition of SmoovPlay without editing upstream's installer/build.py.

It loads installer/build.py, points the in-app updater at our releases and our own signing key, then runs
upstream's build unchanged. Keeping our changes out of upstream's files is what lets the nightly sync merge
SmoovPlay's updates cleanly.

    python kvlr/build_kvlr.py                       # version <upstream>-kvlr.1
    python kvlr/build_kvlr.py --kvlr 3              # version <upstream>-kvlr.3
    python kvlr/build_kvlr.py --version 0.4.0-kvlr.1 --launcher-only

Any other argument goes straight to installer/build.py.

Signing key: %USERPROFILE%\.kvlr-ps5-framegen\update-signing-key.xml (KVLR_FRAMEGEN_SIGNING_KEY overrides).
The first build makes it. It never goes in the repo; back it up, because installed copies only take updates
signed with it.
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_REPO = "KvlrTV/kvlr-ps5-framegen"
SIGNING_KEY = Path(os.environ.get("KVLR_FRAMEGEN_SIGNING_KEY")
                   or Path.home() / ".kvlr-ps5-framegen" / "update-signing-key.xml")
# VS 2022 Build Tools installs to Program Files (x86) on KvlrPC-NEW, which upstream's list doesn't include.
EXTRA_CSC = [Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe")]
# Inputs taken from an installed SmoovPlay (see KVLR.md, "Building"), used when no --chiaki-* is given.
INPUTS = Path(os.environ.get("KVLR_FRAMEGEN_INPUTS") or ROOT.parent / "kvlr-ps5-framegen-inputs")


def load_upstream_build():
    path = ROOT / "installer" / "build.py"
    spec = importlib.util.spec_from_file_location("smoovplay_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("RELEASES_REPO", "SIGNING_KEY", "VERSION", "main"):
        if not hasattr(mod, name):
            sys.exit(f"[kvlr] upstream build.py no longer has {name}; update kvlr/build_kvlr.py")
    return mod


def kvlr_args(argv, upstream_version):
    """Turns --kvlr N into --version <upstream>-kvlr.N, and adds -kvlr.1 when no version is given."""
    out, n, i = [], None, 0
    while i < len(argv):
        if argv[i] == "--kvlr" and i + 1 < len(argv):
            n = argv[i + 1]
            i += 2
            continue
        out.append(argv[i])
        i += 1
    if not any(a == "--version" or a.startswith("--version=") for a in out):
        out += ["--version", f"{upstream_version.split('-')[0]}-kvlr.{n or 1}"]
    return out


def stage_ngx(stage: Path) -> None:
    """KVLR DLSS (framegen/kvlr_dlss.py): kvlr_ngx.dll, built from kvlr/ngx against NVIDIA's DLSS SDK (kept outside the
    repo), plus NVIDIA's DLSS runtime DLLs in object form and their licence, into <app>/ngx. Skipped with a note when
    the SDK isn't on this PC (the app then offers RTX VSR only)."""
    import subprocess
    here = Path(__file__).resolve().parent
    sdk = here.parent.parent / "kvlr-ps5-framegen-inputs" / "dlss-sdk"
    if not (sdk / "include" / "nvsdk_ngx.h").exists():
        print(f"[kvlr] DLSS SDK not found in {sdk}: building without DLSS")
        return
    if subprocess.run([sys.executable, str(here / "ngx" / "build_ngx.py"), "--sdk", str(sdk)]).returncode:
        sys.exit("[kvlr] building kvlr_ngx.dll failed")
    built, dest = here.parent / "installer" / "build" / "ngx", stage / "app" / "ngx"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("kvlr_ngx.dll", "nvngx_dlss.dll", "nvngx_dlssg.dll"):
        shutil.copy2(built / name, dest / name)
    shutil.copy2(sdk / "LICENSE.txt", dest / "NVIDIA-RTX-SDKs-LICENSE.txt")
    print(f"[kvlr] DLSS staged in {dest}")


def apply_branding(build):
    """KVLR name, colours, logo and icon (kvlr/branding.py), on copies: upstream's files stay untouched."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import branding

    build.BUILD.mkdir(parents=True, exist_ok=True)
    root = branding.brand_launcher(build.HERE / "launcher", build.BUILD / "kvlr-brand")
    build.icon_rgba = branding.icon_rgba
    compile_exe, stage_payload = build.compile_exe, build.stage_payload

    def branded_compile(out, sources, icon, resource=None):
        mapped = [root / "launcher" / s.name if Path(s).parent == build.HERE / "launcher" else s for s in sources]
        here, build.HERE = build.HERE, root  # compile_exe finds Ui.xaml and app.manifest under HERE
        try:
            return compile_exe(out, mapped, icon, resource)
        finally:
            build.HERE = here

    def branded_stage(stage, *a, **kw):
        stage_payload(stage, *a, **kw)
        print(f"[kvlr] branded {branding.brand_app(stage)} app files")
        stage_ngx(stage)

    build.compile_exe, build.stage_payload = branded_compile, branded_stage
    print(f"[kvlr] branding: {branding.NAME}, launcher copies in {root}")


def main():
    build = load_upstream_build()
    if "--no-brand" in sys.argv:
        sys.argv.remove("--no-brand")
    else:
        apply_branding(build)
    build.RELEASES_REPO = RELEASES_REPO
    build.SIGNING_KEY = SIGNING_KEY
    if hasattr(build, "CSC_CANDIDATES"):
        build.CSC_CANDIDATES.extend(p for p in EXTRA_CSC if p not in build.CSC_CANDIDATES)
    if (INPUTS / "chiaki-build" / "chiaki.exe").exists():
        os.environ.setdefault("SMOOVPLAY_CHIAKI_BUILD", str(INPUTS / "chiaki-build"))
        os.environ.setdefault("SMOOVPLAY_CHIAKI_SRC", str(INPUTS / "chiaki-ng"))
    sys.argv = [sys.argv[0]] + kvlr_args(sys.argv[1:], build.VERSION)
    print(f"[kvlr] releases repo {RELEASES_REPO}, signing key {SIGNING_KEY}, args {' '.join(sys.argv[1:])}")
    return build.main()


if __name__ == "__main__":
    sys.exit(main())
