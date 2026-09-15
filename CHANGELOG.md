# Changelog

All notable changes to serverjack are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- **One-command managed install.** `scripts/build-release.sh <version>`
  packages a release archive (`dist/serverjack-<version>.tar.gz`) and renders
  `dist/serverjack-bootstrap.sh` from `bootstrap/serverjack-bootstrap.sh.in`,
  with the archive's URL and sha256 embedded. The rendered bootstrap installs
  a specific released version with no git checkout: downloads and verifies
  the archive, extracts it to `~/.local/share/serverjack/releases/<version>/`,
  points `~/.local/share/serverjack/current` at it, writes `install.json`,
  then hands off to that release's own `bin/serverjack-setup`. Refuses to run
  as root or to silently take over an existing (git or managed) install.
- **`bin/serverjack-setup`: the guided part of the one-command install.**
  Runs before `install.sh` (the bootstrap execs it; it's also runnable by
  hand from a checkout, and aliased as `serverjack-ctl setup`), asking on
  `/dev/tty` whatever `install.sh` itself never does — each question backed
  by the same flag `install.sh` takes, so a fully-flagged run never touches a
  terminal at all: confirms a supported OS/architecture with a working
  `systemd --user`; finds actually-missing prerequisites (tmux, curl,
  python3, `ss`, tar, `sha256sum`, `flock`, ca-certificates — derived from
  what the scripts use, not the README's short list) and offers one
  `sudo apt-get update && apt-get install -y ...`; for a genuinely fresh
  install (not yet this account's own), refuses to silently take over an
  unrecognized existing install or another account's serverjack already on
  the target port; offers to install/sign in to Tailscale or skip `tailscale
  serve` entirely for a
  self-managed reverse proxy; if publishing, asks who may reach it
  (`SERVERJACK_ALLOW`) — a detected single tailnet login by default, a typed
  list, or an explicit "yes" before ever leaving it open to the whole
  tailnet; asks whether other Linux accounts share the machine (`--unix`);
  runs the one-time root steps (`loginctl enable-linger`,
  `tailscale set --operator`) inline instead of only printing them, keeping
  another account's existing operator grant unless you say to replace it,
  and offering an alternate `--https-port` rather than overwriting an
  existing foreign `tailscale serve` mapping; then runs `install.sh` and
  verifies units, the loopback health check, and — when publishing — the
  tailnet URL itself before printing the private address. No controlling
  terminal for a still-unanswered question, or a refused/failed sudo step,
  stops cleanly with exactly what's left to do — never a silent fallback to
  a broad-access default. Re-running it on an already-installed account
  shows the current state and offers update / change-allow-list /
  change-publish-settings / leave-it-alone, rather than refusing outright.
  The resolved install flags are recorded in `install.json`'s
  `"install_args"` so a later `serverjack-ctl update` replays the same
  choices instead of reverting to `install.sh`'s own defaults.
- `tests/guided-install.sh`, a container test (the same privileged Debian 13
  systemd fixture as `tests/managed-install.sh`, a fake `tailscale` binary
  standing in for the real one) driving `serverjack-setup` through a REAL pty
  (`tests/guided-install-driver.py`, spawning `script -qfc '...' /dev/null`)
  for: missing prerequisites offered and refused, then offered and accepted
  with Tailscale entirely missing and serve skipped; no controlling terminal
  (clean stop, exit 2); root refused; an unsupported OS refused; Tailscale
  logged out then brought to Running by "up" with the login URL surfaced and
  polled, untagged with the allow-list defaulting to the detected login; a
  tagged node requiring an allow-list; an existing foreign `tailscale serve`
  mapping offered an alternate `--https-port`; "other accounts share this
  machine?" selecting `--unix`; and a rerun that changes nothing when told
  to. Optional, host-side, wired into `bash tests/run.sh`.
- `bin/serverjack-ctl`, a lifecycle helper installed to `~/.local/bin/` for
  every install: `status`, `versions`, `update [--version X]` (stages and
  health-checks a new release without touching the running one, auto-rolling
  back on failure), `rollback`, `uninstall [--yes]` (keeps
  `~/.config/serverjack` and tmux sessions), `prune [--yes]`. Works from the
  terminal even if the web UI is unhealthy.
- `install.sh` now bakes the stable `~/.local/share/serverjack/current/...`
  path into the systemd units when run from inside a managed release
  directory, so a later release only needs its `current` symlink swapped and
  the units restarted, never reinstalled. Git-checkout installs are
  unchanged.
- The "Update serverjack" shortcut and `update_available()` now cover managed
  installs too (running `serverjack-ctl update`), alongside the existing git
  `git pull` behavior; `/api/status` gains a `"channel"` field
  (`"release"`/`"git"`/`"unknown"`).
- `.github/workflows/release.yml`: pushing a `vX.Y.Z` tag builds and attaches
  the release archive, bootstrap and `SHA256SUMS` to a **draft** GitHub
  release (publishing stays a manual step — see CONTRIBUTING.md "Releasing").
- `tests/managed-install.sh`, a container test (privileged Debian 13 systemd,
  no git, no GitHub reachable for the release) proving the whole path: a
  piped install, a rerun preserving env/shortcuts, an update with a live tmux
  session surviving, a broken release being auto-rolled-back, a no-`--yes`
  update with no tty refusing cleanly, an explicit rollback, a truncated
  bootstrap and a corrupted archive both executing/installing nothing, an
  uninstall keeping config and tmux, and root being refused. Optional,
  host-side, wired into `bash tests/run.sh`.

### Changed

- README "Why serverjack" opens with what serverjack does (start an agent in
  the right directory, paste the command it asked for, close finished tmux
  sessions) rather than with checking on a running agent, which is what the
  vendors' remote-control features are for.
- fzf 0.74.4 (was 0.74.3): pinned checksums bumped for the linux_amd64,
  linux_arm64 and linux_armv7 assets in `install.sh`.
- README "Install" section leads with the managed one-command install
  (`curl -fsSL .../serverjack-bootstrap.sh | bash`); the git checkout is now
  documented as the development path. Works once a release with these assets
  exists (v1.4.0 will be the first).

## 1.3.0 - 2026-09-14

### Changed

- Prompt Jack branding: the J-shaped plug and separate terminal chevron now
  appear in page headers, the terminal's All sessions link, and browser and
  home-screen icons. SVG and antialiased PNG icons share the same geometry;
  refreshed icon URLs replace the previously cached artwork.
- README repositioned around "Jack into your server": a demo GIF and a
  five-bullet proof list above the fold, "Why serverjack" reordered to lead
  with the reason the project exists, and a social preview image for link
  previews. No behavior change.
- Added `docs/FAQ.md`, answering the five questions this kind of project
  gets asked first: why not plain ttyd, why not the vendors' own remote
  control, why Tailscale and not a password, whether it phones home, and how
  to run it without Tailscale. Linked from the README's security section and
  its Contents list.

## 1.2.1 - 2026-09-14

### Fixed

- The first card under "Agent servers" had square top corners: the rounding
  rule keyed off the card following the heading directly, and an intro line
  now sits between them. The first card of a run is rounded regardless of
  what precedes it (same for the Sessions list).

## 1.2.0 - 2026-09-14

### Added

- Every way to start a session (the Start a session card, the terminal page's
  "+" popover, `/start`, `/new`/`/api/new`, `/tools/open`, and a run shortcut)
  now takes an optional name. Left blank, the session is named for its type
  and directory instead of a bare kind — a shell in `~/projects/3d-lab`
  becomes `shell-3d-lab`, `sudo apt install ffmpeg` becomes `apt` (or
  `apt-src` run from `~/src`).

### Changed

- Landing page: "Run a command" and "New shell" are replaced by one "Start a
  session" card at the top — Shell (the default) or any installed agent, a
  directory (defaults to `~`), and an optional command for Shell. Picking an
  agent just runs its plain command (`claude`, `codex`, ...) in the chosen
  directory; there's no remote-control/server-mode choice on this card any
  more. The bottom accordion is renamed "Agent servers" and now only lists a
  tool that needs installing, logging in, or has a server/daemon/extra action
  to offer — a tool that's ready with nothing else to configure (just Gemini
  CLI, by default) has no row there any more. Removed the "Open with remote
  control" action from Claude Code's and Copilot's cards (an interactive
  session now starts from the top instead; Claude's Remote Control server is
  unaffected).

## 1.1.0 - 2026-09-13

### Added

- `bin/serverjack --version` and `bin/serverjack --check` (alias `--doctor`), a
  read-only startup diagnosis: Python, tmux and ttyd versions, runtime and
  config directory modes, env-file permissions, Tailscale reachability and
  whether the listen target is free. `install.sh --version` reports the same
  number. The version shows in the page footer and in `/api/status`.
- `docs/ARCHITECTURE.md`: request flow, the security model as implemented, the
  WebSocket proxy, tmux integration, the agent registry and the test strategy.
- `tests/test_unit.py`: 27 unit tests over the pure functions (form limits,
  host validation, allow-list matching, tools.json merge, atomic config
  writes), run before the browser suites.
- A `lint` job in CI: shellcheck, pyflakes and a Python 3.9 compile check.
- `docs/shots/make.sh`: reproducible, neutral README screenshots.

### Changed

- Clone anywhere: the quick start no longer suggests a path, and
  `SERVERJACK_DIRS` defaults to `~/projects:~/src:~/code:~`.
- Fixed the four outstanding shellcheck warnings.

## 1.0.0 - 2026-09-13

First public release.

serverjack is a web front door to a home server, reached over Tailscale from
a phone or a laptop: a landing page that runs a pasted command in a new tmux
session, a session list with one-tap attach, a browser terminal (ttyd behind
serverjack's own proxy) with a phone soft-key row, and cards that launch and
log in to coding-agent CLIs. One Python file, no Node, no sudo.

### Added

- Landing page, session tabs, tmux window picker, phone soft keys, pop-out
  windows, PWA install on iOS, and a CRT effects toggle.
- Agent cards for Claude Code, Codex, OpenCode, GitHub Copilot CLI and Gemini
  CLI, with install and login flows and one-click actions; a JSON registry
  (`tools.json`) for adding or overriding tools.
- Identity from Tailscale headers (`SERVERJACK_ALLOW`), a peer-uid check for
  other local accounts, and a Unix-socket listen mode for shared machines.
- Idempotent `install.sh` and a conservative `uninstall.sh` that only removes
  `tailscale serve` mappings it owns.
- Real-browser test suite (Chromium, Firefox, WebKit with iPhone emulation)
  plus HTTP and wrapper security regressions, run in CI on every push and
  pull request.

### Security

- Request-parsing hardening (body limits, strict `Content-Length`, chunked
  transfer refused), owner-only config files, a restricted
  `TTYD_EXTRA_ARGS` allowlist, and symlink-safe socket handling.

Verified on a clean Debian 13 install. See the
[v1.0.0 release notes](https://github.com/jackgillette006/serverjack/releases/tag/v1.0.0).
