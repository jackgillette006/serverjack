# Changelog

All notable changes to serverjack are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

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
