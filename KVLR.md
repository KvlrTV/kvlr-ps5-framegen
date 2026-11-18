# KVLR edition of SmoovPlay

Private KVLR fork of [smoovplay/smoovplay](https://github.com/smoovplay/smoovplay) (MIT). It plays PS5 games
(GTA VI) on KvlrPC-NEW over Remote Play with RIFE frame generation, and adds KVLR features and UI on top.
The upstream `README.md`, `LICENSE` and `NOTICE` stay as they are.

## Remotes

| Remote | Repo | Use |
|---|---|---|
| `origin` | `KvlrTV/kvlr-ps5-framegen` (private) | ours: push here |
| `upstream` | `smoovplay/smoovplay` | fetch only (push URL set to `DISABLE`) |

## Taking upstream's updates

- `.github/workflows/kvlr-upstream-sync.yml` runs nightly (04:17 UTC) and on demand from the Actions tab.
  - Clean merge: pushed straight to `main`.
  - Conflict, or upstream changed `.github/workflows`: upstream goes on branch `upstream-sync` and a PR opens.
    Finish it locally: `git fetch upstream && git merge upstream/main`.
- By hand at any time: `git fetch upstream && git merge upstream/main && git push`.

## Rules that keep merges clean

1. Put KVLR code in new files under `kvlr/` (or new launcher pages/modules) wherever possible.
2. When an upstream file must change, keep the edit small and mark it with a `KVLR:` comment so a conflict is
   easy to read.
3. Never edit `VERSION` or `RELEASES_REPO` in `installer/build.py`; `kvlr/build_kvlr.py` sets them.

## KVLR features

| Feature | Files | Upstream hooks (marked `KVLR:`) |
|---|---|---|
| Settings registry additions | `framegen/kvlr_settings.py` | `framegen/settings.py` (appends to `SPECS`), `framegen/menu.py` (launcher-only groups stay out of the in-video menu), one assertion in `tests/test_settings.py` |
| OBS output: a clean picture (no menu, stats or notes) sent to OBS through Spout, 4K/1440p/1080p at 60 or 30 fps | `framegen/kvlr_obs.py` | `framegen/io.py` (made in `GLWindowSink.__init__`, called in `write()` before the UI is drawn, closed in `close()`); `SpoutGL==0.1.1` in `installer/requirements-runtime.txt` |

OBS output: Settings → OBS output → On. In OBS, install the Spout2 plugin for OBS, add a **Spout2 Capture** source and
pick **KVLR PS5**. Fullscreen on a 4K monitor with a 4K feed, OBS gets exactly what's on screen (look included);
otherwise the feed is FSR-upscaled from the source frame, without the look. Off with HDR output.
`FRAMEGEN_OBS_TEST=1` logs every send.

## Building and releasing

- Build: `python kvlr/build_kvlr.py --kvlr N` gives version `<upstream>-kvlr.N` (for example `0.3.1-kvlr.1`).
  It runs upstream's `installer/build.py` unchanged, with the updater pointed at `KvlrTV/kvlr-ps5-framegen` and our
  own signing key. Upstream's build prerequisites apply (see `installer/README.md`).
- Inputs (kept outside the repo in `..\kvlr-ps5-framegen-inputs\`, which the wrapper finds on its own;
  `KVLR_FRAMEGEN_INPUTS` overrides). All of them come from an installed SmoovPlay
  (`%LOCALAPPDATA%\Programs\SmoovPlay`), so nobody has to build chiaki-ng:
  - `chiaki-build\`: the installed `chiaki\` folder without `licenses\`, `source\` and `LICENSE-AGPL-3.0.txt`.
  - `chiaki-ng\`: `git clone --depth 1 -b v1.10.1 https://github.com/streetpea/chiaki-ng`, then `git apply` the installed
    `chiaki\source\chiaki-ng-v1.10.1-frametap.patch` and copy its `frametap*` files into `gui\src` / `gui\include`.
    Add `ffmpeg-kvlr-win64-gpl-shared-from-install\LICENSE.txt` (the installed `licenses\FFmpeg-LICENSE.txt`).
  - `models\flownet_v4.22.lite.pkl` in the repo (gitignored), from the installed `app\models\`.
  When upstream moves to a newer chiaki-ng, redo these from the newer install.
- Signing key: `%USERPROFILE%\.kvlr-ps5-framegen\update-signing-key.xml`, made by the first build, never in git.
  Installed copies only accept updates signed with it. Backed up in KVLR Vault (kvlr-stack secrets, scope `infra`) as
  `KVLR_FRAMEGEN_UPDATE_SIGNING_KEY`; on a new build PC restore it with
  `kvlr-secret run --scope infra -- python -c "import os,pathlib; p=pathlib.Path.home()/'.kvlr-ps5-framegen'/'update-signing-key.xml'; p.parent.mkdir(exist_ok=True); p.write_text(os.environ['KVLR_FRAMEGEN_UPDATE_SIGNING_KEY'])"`.
- Release: run `release.yml` from the Actions tab (it drafts the release), upload
  `installer/dist/SmoovPlay-Setup.exe` and its `.sig`, then publish.
- The repo is private, so the in-app update check needs `SMOOVPLAY_GITHUB_TOKEN` (a read-only token) set on the
  PC that runs it, or the repo made public.
