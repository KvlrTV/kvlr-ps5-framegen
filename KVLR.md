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
| Settings registry additions | `framegen/kvlr_settings.py` | `framegen/settings.py` (appends to `SPECS`), `framegen/menu.py` (launcher-only groups stay out of the in-video menu), two assertions in `tests/test_settings.py` |
| OBS output: a clean picture (no menu, stats or notes) sent to OBS through Spout, 4K/1440p/1080p at 60 or 30 fps | `framegen/kvlr_obs.py` | `framegen/io.py` (made in `GLWindowSink.__init__`, called in `write()` before the UI is drawn, closed in `close()`); `SpoutGL==0.1.1` in `installer/requirements-runtime.txt` |

**Branding** (`kvlr/branding.py`, `kvlr/brand/kvlr-mark.png`) touches no upstream file. At build time it brands
*copies*: the launcher's C# and XAML are copied to `installer/build/kvlr-brand/` and compiled from there, and the
staged app's Python is branded in place. It changes the visible name (KVLR PS5 Frame Gen; "KVLR PS5" on the rail),
maps SmoovPlay's amber palette to KVLR's (cyan accent, gold, red, green, darker greys), swaps the rail logo and app
icon for the KVLR mark with neon controller symbols (triangle, circle, cross, square) round the tile's edge (KR alone
at 32 px and below; generic shapes, no PlayStation logo), and credits SmoovPlay (MIT) in the rail footer. Names Windows and the disk use stay
SmoovPlay's (install folder, shortcuts, registry key, `%APPDATA%\framegen`, `SMOOVPLAY_*`, the update-signature
header), so updates and settings carry on. If upstream reshapes the rail logo or footer, the build stops with a
message naming the function to update. `python kvlr/build_kvlr.py --no-brand` builds without it.

**One-click PS5 connect** (`framegen/kvlr_settings.py` settings `ps5_console`, `ps5_codec`, `ps5_bitrate`, launcher-only
group "PS5 connection"; `installer/launcher/KvlrChiaki.cs`; hooks marked `KVLR:` in `Core.cs` before the Play flow's
`Chiaki.Start` and in `Ui.cs` `OpenChiaki`). Before Play starts chiaki-ng, the launcher writes the choices into
chiaki-ng's saved settings (`HKCU\Software\Chiaki\Chiaki\settings`): `auto_connect_mac` = the chosen registered
console's `server_mac`, so chiaki-ng finds it, wakes it and streams straight away; codec H.265 (H.265 HDR with HDR
output on, so the two always match); local bitrate. "Ask each time" removes `auto_connect_mac`, and the guide's Open
chiaki-ng removes it too so the console list (and Register) shows. The console list comes from chiaki-ng's
`registered_hosts`, read when the Settings page loads. The Play page shows the chosen console as a chip with its state
(Ready / Resting / Not found, from a PlayStation discovery broadcast every 6 s while the page is up) and says Play
connects to it by itself (`installer/launcher/KvlrUi.cs`; hooks in `Ui.cs` `BuildChips` and the idle subtitle).
**Stop ends Remote Play** (setting `ps5_on_stop`: end / rest / keep, default end). After a Remote Play session stops
or ends, the launcher closes the chiaki-ng it started, with chiaki-ng's `disconnect_action` set first (`sleep` asks
the PS5 into rest mode, `nothing` leaves it on), so the stream doesn't carry on in chiaki-ng's window. While playing,
**Rest PS5** next to the console chip does the rest-mode stop once (`KvlrUi.cs` `KvlrOnState`, hook in `Ui.cs`'s play
state handler; `KvlrChiaki.EndRemotePlay`).

**Hold Esc to stop** (`framegen/kvlr_keys.py`; hooks in `io.py` `_on_key` and `_events`): Esc or Q must be held for
5 s, then a confirmation asks (Enter stops, any other key keeps playing, it lapses after 8 s); the menu keeps its own
Esc. When Stop ends Remote Play, `run.py` no longer restores chiaki-ng's window on exit (marked hook), so nothing
jumps to another monitor before the launcher closes it. The on-screen wording ("Esc: quit" and the like) is swapped
by the branding layer's `TEXT_SWAPS`.

**4K capture cards** (`framegen/kvlr_capture.py`, setting `capture_work`, launcher-only group "Capture card"; hook in
`run.py` after the settings load). Since 0.3.7 upstream asks the card for the size in its own Picture → "Capture card
resolution" (1080p, 1440p or 4K), so our old `capture_size` setting was dropped at the 0.3.9 merge. Frame generation
then works at the "work size": Auto is 1080p for 90 and 120 fps, and at 60 fps the captured size with NVIDIA VFG
low/medium, 1440p otherwise; the window and OBS output upscale back. `kvlr/bench_4k.py` times the models at each size
(results stay local, in `installer/build/`, because NVIDIA's VFG licence forbids publishing them). The console must send
SDR (10-bit HDR isn't read). An Elgato Cam Link 4K takes 4K at up to 30 fps only (1080p at 60).

**One taskbar button** (`installer/launcher/KvlrTaskbar.cs`, hook in `Ui.cs` `Wire`): the launcher, the pipeline's
video window and the chiaki-ng it started get the same `System.AppUserModel.ID` (`KvlrTV.KvlrPS5FrameGen`) plus the
relaunch name and KVLR icon, set through each window's property store every 2 s, so Windows groups them under one
button. The video window's own icons (`framegen/assets/icon_*.png`) are swapped for the KVLR icon by the branding.

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
