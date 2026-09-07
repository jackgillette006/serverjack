# Contributing

serverjack is a small, finished tool. Contributions are welcome when they keep
it that way.

## Scope

In scope:

- Opening, closing and attaching to tmux sessions from a phone or a desktop.
- Running a pasted command in a visible terminal (the `sudo` case).
- Getting coding CLIs installed, logged in and started, including their own
  remote-control servers. Adding or fixing a tool in the registry is the most
  useful kind of change: vendors move fast, and a registry entry is a few
  lines in `BUILTIN_TOOLS`.
- Anything that keeps the "one stdlib Python file, one downloaded ttyd, no
  root" install true on more Linux machines.

Out of scope, on purpose:

- Agent status, notifications, chat or transcript views. Claude Code, Codex,
  Copilot CLI and OpenCode ship their own remote control; serverjack handles
  the server, they handle the agent.
- Built-in authentication. serverjack is meant to live behind `tailscale
  serve` or an authenticating reverse proxy, and a home-grown login would
  invite people to expose it. See the security section of the README.
- Dependencies. No pip packages, no Node, no compiled extensions, no CDN
  assets, no webfonts.

## Ground rules

- `bin/serverjack` stays one file, Python 3.9+ syntax, stdlib only.
- The visual layer follows `docs/design/DESIGN.md`. Don't add one-off colours,
  radii or fonts; add a token if a genuinely new semantic role is missing.
- The terminal is ttyd's xterm.js. Don't theme it from serverjack.
- Real-browser tests live in `tests/`. `bash tests/run.sh` needs docker and a
  running ttyd. Keep the selectors those tests use, or update the tests with
  the change. `docs/MANUAL-TESTS.md` covers what only a real phone can prove.
- Run `bash install.sh` after pulling; it is idempotent.

## Reporting a bug

Include the output of `journalctl --user -u serverjack -n 50`, the browser
and device, and, for a tool problem, the tool's version and how it was
installed.
