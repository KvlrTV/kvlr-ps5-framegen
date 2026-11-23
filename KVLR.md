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
| **Private build only.** Remote Play output: the clean picture for KVLR Remote Play (KVLR Bridge `remote_play`, remotegta6.kvlrtv.com), copied into shared memory `Local\kvlr-remote-frames` by an asynchronous GPU readback, only while the bridge holds it open. Spout gets ~12 fps across processes from this window and Windows' capture none, so it has its own path | `framegen/kvlr_remote.py` | `framegen/io.py` (made beside the OBS feed in `GLWindowSink.__init__`, called in `write()` before stats and menu, closed in `close()`) |

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

**30 fps capture modes** (`Every60` in `framegen/kvlr_capture.py`, applied by the same `wrap()` hook): a card that
sends about 30 fps (a UGREEN 25773 at 1440p, its largest size) is put on a 60 Hz beat, each frame handed on once more
half a frame after it arrived, so the pipeline sees a 30 fps game on a 60 Hz signal and generates frames. Without it
every frame was new, the pipeline took the game to be at 60 fps and made no AI frames. Measured 2026-11-19 on
KvlrPC-NEW, GTA VI over a UGREEN 25773, about 38 s each, dropped capture frames: 1080p60 at 120 fps 39-40;
1440p30 at 120 fps 19 with VFG medium but 248 with VFG high (too slow); 1440p30 at 60 fps (works at 1440p) 18.

**One taskbar button** (`installer/launcher/KvlrTaskbar.cs`, hook in `Ui.cs` `Wire`): the launcher, the pipeline's
video window and the chiaki-ng it started get the same `System.AppUserModel.ID` (`KvlrTV.KvlrPS5FrameGen`) plus the
relaunch name and KVLR icon, set through each window's property store every 2 s, so Windows groups them under one
button. The video window's own icons (`framegen/assets/icon_*.png`) are swapped for the KVLR icon by the branding.

**NVIDIA DLSS (0.4.0)** (`kvlr/ngx/kvlr_ngx.cpp`, our own code; `framegen/kvlr_dlss.py`, `framegen/kvlr_dlssg.py`). A native
helper, `kvlr_ngx.dll` (Direct3D 12 + NVIDIA NGX), takes frames from the CUDA pipeline through buffers shared between
Direct3D 12 and CUDA, and measures motion with NVIDIA Optical Flow (the hardware engine, on CUDA; pixels from each frame
back to the one before, DLSS's convention, checked against a known 16 px shift).
- **DLSS SR**: Picture → Upscaler RTX VSR → AI upscaler "NVIDIA DLSS SR" (settings `ai_upscaler`, `dlss_preset`,
  `dlss_motion`; switches live). The window's RTX VSR slot holds a `KvlrUpscaler` that picks RTX VSR or DLSS per frame;
  both write packed RGB10A2. Hooks in `framegen/io.py` `_vsr_ready` and `_name`.
- **DLSS Frame Generation**: a third AI engine, `model = "dlssg"` ("NVIDIA DLSS FG"), next to RIFE and NVIDIA VFG, with
  VFG's interface; 1, 2 or 3 generated frames per real pair for 60 / 90 / 120 fps (multi-frame on RTX 50), the requested
  fraction taken to the nearest; Steady HUD as with VFG; falls back to RIFE if it can't start. Constant depth and identity
  camera matrices (captured video has no game data). Hooks marked `KVLR:` in `framegen/settings.py` (the choice) and
  `run.py` (session_config, build, fallback, labels), plus `autodetect.py`, `kvlr_capture.py`, the launcher's Play chip.
  On a 16 px pan its frames match the true in-between positions at 68.5 dB (a blend: 27-29 dB), at 2x and 4x.
- **NVIDIA's files stay out of this repo** (NVIDIA RTX SDKs licence): the DLSS SDK is cloned to
  `..\kvlr-ps5-framegen-inputs\dlss-sdk` (NVIDIA/DLSS, sparse: include, lib/Windows_x86_64/rel and x64, doc,
  LICENSE.txt) and the Optical Flow SDK headers (BSD) to `..\kvlr-ps5-framegen-inputs\nvof`. `kvlr/ngx/build_ngx.py`
  builds the DLL with MSVC (no CUDA toolkit: `kvlr/ngx/cuda_stub/cuda.h`); `kvlr/build_kvlr.py` stages it, NVIDIA's
  `nvngx_dlss.dll` / `nvngx_dlssg.dll` (object form, as the licence allows) and the licence text into `<app>/ngx`.
  Without the SDK the build goes on without DLSS. Checks: `kvlr/ngx/test_sr.py`, `test_dlss_cuda.py`, `test_dlssg.py`.

**Settings page layout (0.4.0)** (`installer/launcher/KvlrSettingsLayout.cs`, hooks in `SettingsPage.cs` BuildSettings
and the end of RefreshSettings; approved mockup `kvlr/design/settings-layout-mockup.png`): tabs Quality / Frame Gen /
Colour / Stream / Display filter the cards, a processing-order strip shows what runs on each frame, and the Frame
generation, Look and OBS output cards get an on/off switch. Not done yet: the mockup's live stats panels.

**Play page capture row** (`installer/launcher/KvlrCaptureRow.cs`, hook in `Ui.cs` BuildDevices): Capture size, AI frames
size and Output (30 = frame generation off, 60/90/120, live) under the capture card's Card / Sound row.

**Versions**: from 0.4.0 the KVLR edition has its own numbers (`python kvlr/build_kvlr.py --version 0.4.0`), still built
on upstream SmoovPlay (0.3.9 at 0.4.0).

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
- **Two builds, one set of releases** (`installer/launcher/KvlrChannel.cs`, hook in `Updater.cs` `GitHub.SetupName` and
  `Newest`; `kvlr/build_kvlr.py --private`):
  - **Public** (`python kvlr/build_kvlr.py --version X`): `SmoovPlay-Setup.exe` + `.sig`, what gta.kvlrtv.com and
    friends get. Leaves out the private-only app files (`PRIVATE_APP_FILES` in `build_kvlr.py`: `framegen/kvlr_remote.py`).
  - **Private**, Kev's own (`python kvlr/build_kvlr.py --version X --private`, after the public one): everything,
    written as `installer/dist/KVLR-Private-Setup.exe` + `.sig`.
  - Both go up to the **same release**, same version, same signing key. Each copy only updates from its own setup and
    skips a release that doesn't have it, so a public copy never turns private and the reverse. A public-only release
    is fine; Kev's copy waits for the next release with a private setup.
  - The repo is public, so the private setup can be downloaded by anyone who goes looking on the releases page. It is
    private by channel, not secret (its source is in this repo anyway).
  - Moving a copy across: run the other setup once by hand; it then follows that channel.
  - Checked 2026-11-23 against a stand-in releases API: the public 0.4.15 build took a public-only 0.4.16 and the
    private build skipped it for its own 0.4.15 file; drafts ignored.
- Release: run `release.yml` from the Actions tab (it drafts the release), upload
  `installer/dist/SmoovPlay-Setup.exe` and its `.sig` (and `KVLR-Private-Setup.exe` and its `.sig` when there's a
  private build), then publish.
- The repo is public, so the in-app update check works on any PC with no token: every installed copy offers the
  newest published release signed with our key. Download page for friends: `https://gta.kvlrtv.com`, which links to
  the latest release's `SmoovPlay-Setup.exe`, so it never needs changing when a new release goes out.

**Automatic updates (0.4.14)** (`installer/launcher/KvlrUpdates.cs`, hooks in `Ui.cs` StartLauncher, which calls
KvlrUpdateStart instead of UpdateCheck.Start, and ShowUpdate, whose link goes to gta.kvlrtv.com): when the launcher opens,
and every 3 hours while it is open, it asks GitHub for the newest release (no 6-hour cache). A newer one opens "Update to
vX?" (Update now / Not now / All versions), which installs it through upstream's signed RunUpdate after a 15-second
countdown. No prompt while playing, saving a clip or over another dialog, or for copies that can't update themselves. The
newest version a PC has run is kept in `%APPDATA%\framegen\kvlr-highest-version.txt`. A copy rolled back below it only
gets the prompt for a release newer than that version; the rail link still shows. gta.kvlrtv.com lists every release
with its setup (`#versions`) for rolling back, and the Help page has an "All versions" link. Tested 2026-11-21 against a
local stand-in API (`SMOOVPLAY_RELEASES_API`): 0.4.14 auto-installed a signed 0.4.15-rc.1, and after rolling back to
0.4.14 it showed no prompt. An update fails if a second launcher window still holds `SmoovPlay.exe`; Retry fixes it
once that window is closed.

**One-wizard install (0.4.13)** (`installer/launcher/KvlrSetup.cs`, hooks in `Core.cs` Installer.Run and `Ui.cs`
RunChecks / CheckNext / StartInstall; `kvlr/build_kvlr.py` stage_vc_redist): Microsoft's Visual C++ redistributable ships
in the setup (`app\redist`, Authenticode-checked at build and before it runs) and the install step runs it when it's
missing, so the PC check shows it as "Comes with KVLR PS5 Frame Gen" instead of a fix to press. The folder page has an
optional, unticked **NVIDIA VFG** box (RTX 40/50 only; ticking it accepts NVIDIA's licence, linked) that downloads VFG from
NVIDIA during the install, before the graphics-card step; a failed VFG download never fails setup. NVIDIA's files are
never bundled. `framegen/kvlr_settings.py kvlr_defaults()`: Kev's `model: vfg` default applies only where VFG is set up.

**Other settings (0.4.12)** (`installer/launcher/KvlrOtherSettings.cs`, hooks in `SettingsPage.cs` and the tab click in
`KvlrSettingsLayout.cs`): in each Settings card, rows that aren't in use (a switch that's off, a choice at Off / None / 0,
a setting not used with the picked source, and anything that only applies with one of those) fold under "Other settings
(N)". Worked out when the page opens or a tab is picked, so rows don't jump while you use them.
