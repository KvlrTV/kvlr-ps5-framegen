r"""Builds the KVLR edition of SmoovPlay without editing upstream's installer/build.py.

It loads installer/build.py, points the in-app updater at our releases and our own signing key, then runs
upstream's build unchanged. Keeping our changes out of upstream's files is what lets the nightly sync merge
SmoovPlay's updates cleanly.

    python kvlr/build_kvlr.py                       # version <upstream>-kvlr.1
    python kvlr/build_kvlr.py --kvlr 3              # version <upstream>-kvlr.3
    python kvlr/build_kvlr.py --version 0.4.0-kvlr.1 --launcher-only
    python kvlr/build_kvlr.py --version 0.4.15 --private   # Kev's private build (see PRIVATE below)

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
# Two builds share one set of releases (installer/launcher/KvlrChannel.cs). The private one is Kev's own: it adds the
# files below and installs/updates from KVLR-Private-Setup.exe on the same release; the public one leaves them out.
PRIVATE_SETUP = "KVLR-Private-Setup.exe"
PRIVATE_APP_FILES = ["framegen/kvlr_remote.py"]  # KVLR Remote Play output


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
    # Depth Anything V2 Small (Apache-2.0) for DLSS FG's estimated depth (framegen/kvlr_depth.py)
    depth = sdk.parent / "depth" / "depth_anything_v2_small_fp16.onnx"
    if depth.exists():
        shutil.copy2(depth, stage / "app" / "models" / depth.name)
        lic = depth.with_name("LICENSE-depth-anything-v2-small.txt")
        if lic.exists():
            shutil.copy2(lic, stage / "app" / "models" / lic.name)
        print(f"[kvlr] depth model staged ({depth.stat().st_size // 1_000_000} MB)")
    else:
        print(f"[kvlr] depth model not found ({depth}): DLSS FG depth will be unavailable")
    print(f"[kvlr] DLSS staged in {dest}")


VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def stage_vc_redist(stage: Path) -> None:
    """Microsoft's Visual C++ 2015-2022 redistributable (x64), into <app>/redist, so setup installs it itself
    (installer/launcher/KvlrSetup.cs) instead of asking the player to fetch it. Microsoft lets it be shipped with an
    app. Cached in the inputs folder (delete redist\vc_redist.x64.exe there for a newer one). Its Authenticode signature must be valid and
    Microsoft's, here and again on the player's PC before it runs."""
    import subprocess
    import urllib.request
    cached = INPUTS / "redist" / "vc_redist.x64.exe"
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        print(f"[kvlr] downloading {VC_REDIST_URL}")
        urllib.request.urlretrieve(VC_REDIST_URL, cached)
    sig = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"$s = Get-AuthenticodeSignature -LiteralPath '{cached}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\""],
                         capture_output=True, text=True).stdout.strip()
    if not sig.startswith("Valid|") or "O=Microsoft Corporation" not in sig:
        sys.exit(f"[kvlr] {cached} isn't validly signed by Microsoft ({sig}); delete it and build again")
    dest = stage / "app" / "redist"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, dest / cached.name)
    print(f"[kvlr] Visual C++ runtime staged ({cached.stat().st_size // 1_000_000} MB)")


def strip_private(stage: Path) -> None:
    """Public build: the private-only app files come out of the staged app (io.py copes with their absence)."""
    for rel in PRIVATE_APP_FILES:
        f = stage / "app" / rel
        if f.exists():
            f.unlink()
    print(f"[kvlr] public build: left out {', '.join(PRIVATE_APP_FILES)}")


def make_private(root: Path) -> None:
    """Private build: its branded launcher copy says so, which picks its own setup on each release."""
    f = root / "launcher" / "KvlrChannel.cs"
    src = f.read_text(encoding="utf-8")
    new = src.replace('public const string Name = "public";', 'public const string Name = "private";')
    if new == src:
        sys.exit("[kvlr] KvlrChannel.cs no longer has the channel line; update kvlr/build_kvlr.py")
    f.write_text(new, encoding="utf-8")
    print("[kvlr] private build: channel private, setup " + PRIVATE_SETUP)


def apply_branding(build, private=False):
    """KVLR name, colours, logo and icon (kvlr/branding.py), on copies: upstream's files stay untouched."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import branding

    build.BUILD.mkdir(parents=True, exist_ok=True)
    root = branding.brand_launcher(build.HERE / "launcher", build.BUILD / "kvlr-brand")
    if private:
        make_private(root)
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
        stage_vc_redist(stage)
        if not private:
            strip_private(stage)

    build.compile_exe, build.stage_payload = branded_compile, branded_stage
    print(f"[kvlr] branding: {branding.NAME}, launcher copies in {root}")


def main():
    build = load_upstream_build()
    private = "--private" in sys.argv
    if private:
        sys.argv.remove("--private")
    if "--no-brand" in sys.argv:
        if private:
            sys.exit("[kvlr] --private needs the branding (it lives in the branded launcher copy)")
        sys.argv.remove("--no-brand")
    else:
        apply_branding(build, private)
    build.RELEASES_REPO = RELEASES_REPO
    build.SIGNING_KEY = SIGNING_KEY
    if hasattr(build, "CSC_CANDIDATES"):
        build.CSC_CANDIDATES.extend(p for p in EXTRA_CSC if p not in build.CSC_CANDIDATES)
    if (INPUTS / "chiaki-build" / "chiaki.exe").exists():
        os.environ.setdefault("SMOOVPLAY_CHIAKI_BUILD", str(INPUTS / "chiaki-build"))
        os.environ.setdefault("SMOOVPLAY_CHIAKI_SRC", str(INPUTS / "chiaki-ng"))
    sys.argv = [sys.argv[0]] + kvlr_args(sys.argv[1:], build.VERSION)
    print(f"[kvlr] releases repo {RELEASES_REPO}, signing key {SIGNING_KEY}, {'private' if private else 'public'} "
          f"build, args {' '.join(sys.argv[1:])}")
    rc = build.main()
    if rc == 0 and private:
        # upstream writes SmoovPlay-Setup.exe; the private one goes up to the same release under its own name
        # (the .sig vouches for the file's hash and version, not its name). A public build afterwards won't clobber it.
        dist = build.DIST
        for ext in ("", ".sig"):
            src, dst = dist / ("SmoovPlay-Setup.exe" + ext), dist / (PRIVATE_SETUP + ext)
            if src.exists():
                src.replace(dst)
        print(f"[kvlr] private setup: {dist / PRIVATE_SETUP} (+ .sig); upload both to the release with the public pair")
    return rc


if __name__ == "__main__":
    sys.exit(main())
