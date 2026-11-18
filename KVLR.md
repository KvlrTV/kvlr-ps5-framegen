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

## Building and releasing

- Build: `python kvlr/build_kvlr.py --kvlr N` gives version `<upstream>-kvlr.N` (for example `0.3.1-kvlr.1`).
  It runs upstream's `installer/build.py` unchanged, with the updater pointed at `KvlrTV/kvlr-ps5-framegen` and our
  own signing key. Upstream's build prerequisites apply (see `installer/README.md`).
- Signing key: `%USERPROFILE%\.kvlr-ps5-framegen\update-signing-key.xml`, made by the first build, never in git.
  Installed copies only accept updates signed with it, so back it up.
- Release: run `release.yml` from the Actions tab (it drafts the release), upload
  `installer/dist/SmoovPlay-Setup.exe` and its `.sig`, then publish.
- The repo is private, so the in-app update check needs `SMOOVPLAY_GITHUB_TOKEN` (a read-only token) set on the
  PC that runs it, or the repo made public.
