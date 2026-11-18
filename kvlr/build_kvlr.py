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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES_REPO = "KvlrTV/kvlr-ps5-framegen"
SIGNING_KEY = Path(os.environ.get("KVLR_FRAMEGEN_SIGNING_KEY")
                   or Path.home() / ".kvlr-ps5-framegen" / "update-signing-key.xml")


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


def main():
    build = load_upstream_build()
    build.RELEASES_REPO = RELEASES_REPO
    build.SIGNING_KEY = SIGNING_KEY
    sys.argv = [sys.argv[0]] + kvlr_args(sys.argv[1:], build.VERSION)
    print(f"[kvlr] releases repo {RELEASES_REPO}, signing key {SIGNING_KEY}, args {' '.join(sys.argv[1:])}")
    return build.main()


if __name__ == "__main__":
    sys.exit(main())
