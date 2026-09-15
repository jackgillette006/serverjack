# Changelog

All notable changes to serverjack are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed

- Terminal uses the app's color theme by default (`SERVERJACK_TERM_THEME=off`
  to keep ttyd's default).
- README "Why serverjack" opens with what serverjack does (start an agent in
  the right directory, paste the command it asked for, close finished tmux
  sessions) rather than with checking on a running agent, which is what the
  vendors' remote-control features are for.
- fzf 0.74.4 (was 0.74.3): pinned checksums bumped for the linux_amd64,
  linux_arm64 and linux_armv7 assets in `install.sh`.
- The deny page (wrong tailnet user) and the "terminal unavailable" page no
  longer link a manifest and icons a client in either state can't use — both
  are error interstitials, not something to "Add to Home Screen".
- `ICON_REV`, the icon/manifest cache-buster, is now a hash of the Prompt
  Jack artwork and `VERSION` instead of a hand-maintained string, so any
  future artwork change refreshes cached browsers on its own; icon and
  manifest responses also carry an `ETag`.
- `docs/shots/fixture.sh` factors out the isolated-instance setup previously
  duplicated between `docs/shots/make.sh` and `make-gif.sh`, so the README
  stills and the demo GIF are built from identical fixture data (down to the
  Start card's "Runs `claude`" hint, now shown in both).
- `docs/shots/make-social.sh` renders `social-preview.tmpl.html` using the
  real color tokens and Prompt Jack mark loaded from `bin/serverjack` itself,
  instead of a hand-copied stylesheet and SVG path data that could drift from
  what actually ships; `gif_record.py`'s tap-ring color now reads `--accent`
  off the live page instead of a hardcoded hex.

### Fixed

- A coding CLI installed under a private PATH entry (nvm's versioned bin
  dir, a tool's own `"paths"` glob in `tools.json`) showed as installed and
  its Start card pill appeared, but starting it failed with "command not
  found": Debian's `/etc/profile` resets `PATH` inside the login shell that
  runs the command. `command_args()` now re-exports `TOOL_PATH` as the first
  thing that login shell does, after its own startup files (and their PATH
  reset) have already run — the configured command text itself is left
  exactly as configured, never rewritten to an absolute path, so the echoed
  `$ claude` line and the pane's reported process name still just name the
  tool instead of baking in TOOL_PATH's real location.
- The demo GIF had a flat grey letterbox band across the bottom fifth of
  every frame: the recorded video's pixel size didn't match the emulated
  iPhone's real viewport. `gif_record.py` now derives the recording size
  from the device's own viewport and scale factor instead of a stale
  hardcoded size, and `make-gif.sh` verifies the rendered video isn't
  letterboxed (with a detected-crop fallback) before converting it.
- `docs/shots/make-gif.sh`: a process-wide `export HOME` meant for tmux
  sessions was also stripping Docker's own config from every later `docker`
  call the script made; HOME is now scoped to the tmux session's environment
  instead. A missing session name from the recorder now fails the script
  instead of silently overwriting `demo.gif` with a blank capture.

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
