# Contributing

serverjack is intentionally small. Contributions are welcome when they keep
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

Useful contributions, if you're looking for a place to start:

- Reliable mobile input (keyboard quirks, paste, the phone soft-key row).
- Reconnection after a dropped network or a sleeping phone.
- Installation on more Linux distributions.
- Coexistence with desktop tmux clients attached to the same session.
- Following a coding agent CLI's own command changes (install, login, server).

Out of scope, on purpose:

- Agent status, notifications, chat or transcript views. Claude Code, Codex,
  Copilot CLI and OpenCode ship their own remote control; serverjack handles
  the server, they handle the agent.
- Built-in authentication. serverjack is meant to live behind `tailscale
  serve` or an authenticating reverse proxy, and a home-grown login would
  invite people to expose it. See the
  [security model](README.md#security-model-read-this-first) in the README.
  Identity comes from Tailscale's headers, never from a password serverjack
  invents: `SERVERJACK_ALLOW` filters on `Tailscale-User-Login`. Keeping
  *local* accounts out is a different problem with a different answer -- the
  peer-uid check on the single listening socket, which covers the terminal
  too because serverjack proxies it -- and that is not a login either.
- Dependencies. No pip packages, no Node, no compiled extensions, no CDN
  assets, no webfonts.

## Ground rules

- `bin/serverjack` stays one file, Python 3.9+ syntax, stdlib only.
- The visual layer follows `docs/design/DESIGN.md`. Don't add one-off colors,
  radii or fonts; add a token if a genuinely new semantic role is missing.
- The terminal is ttyd's xterm.js. Its color theme is generated from the app
  tokens (`bin/serverjack`'s `_term_theme()`, see `docs/design/DESIGN.md`'s
  "Terminal theme" section) -- change `TOKENS`, not the terminal.
- Real-browser tests live in `tests/`. `bash tests/run.sh` needs docker and
  nothing else -- it starts its own serverjack and ttyd. Keep the selectors
  those tests use, or update the tests with the change.
  `docs/MANUAL-TESTS.md` covers what only a real phone can prove.
- Run `bash install.sh` after pulling; it is idempotent.

## Before opening a pull request

1. Explain the user-visible problem and the behavior after your change.
2. Keep the change focused and update the README when commands, configuration,
   or security assumptions change. Add an entry under `Unreleased` in
   [CHANGELOG.md](CHANGELOG.md) for anything user-facing.
3. Run `bash tests/run.sh` (needs Docker; it starts its own serverjack and
   ttyd, nothing else has to be running — this also runs
   `tests/managed-install.sh` if Docker can run `--privileged` containers
   with real systemd; it skips itself with a message otherwise). If Docker is
   unavailable, say which checks you could run and which remain unverified.
4. Check screenshots and logs before attaching them. Remove usernames, home
   directories, hostnames, tailnet names, login identities, tokens, session
   links, and unrelated terminal history.

Pull requests from forks are treated as untrusted input. Maintainer automation
labels them but never checks out or executes their code with a write token.

## Releasing

1. Bump `VERSION` in `bin/serverjack`.
2. Add a dated section to [CHANGELOG.md](CHANGELOG.md), moving the
   `Unreleased` entries under it.
3. Commit, then tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. `.github/workflows/release.yml` checks out that tag, verifies `VERSION`
   matches it, runs `scripts/build-release.sh X.Y.Z`, and opens a **draft**
   GitHub release with three assets: `serverjack-X.Y.Z.tar.gz`,
   `serverjack-bootstrap.sh`, `SHA256SUMS`. Wait for that workflow to finish.
5. Verify the draft before publishing it — this step is manual on purpose:
   - Download all three assets and confirm their digests against
     `SHA256SUMS` (`sha256sum -c SHA256SUMS`).
   - `tar tzf serverjack-X.Y.Z.tar.gz` — check the top-level directory name
     and that `bin/`, `systemd/`, `install.sh`, `uninstall.sh`, `LICENSE`,
     `README.md`, `CHANGELOG.md`, `docs/FAQ.md` and `RELEASE` are all there.
   - Skim `serverjack-bootstrap.sh` for the embedded version, URL and sha256
     matching this release.
   - Optionally run `tests/managed-install.sh` (or the relevant parts of it
     by hand) against the draft's assets before publishing.
6. Publish the draft release on GitHub. `serverjack-bootstrap.sh`'s stable
   `.../releases/latest/download/...` URL and the GitHub API's "latest
   release" (what `serverjack-ctl update` resolves against with no
   `--version`) only see it from this point.

## Reporting a bug

Include the output of `journalctl --user -u serverjack -n 50`, the browser
and device, and, for a tool problem, the tool's version and how it was
installed. Review logs before posting: paths, commands, tailnet identities and
tool output can contain private information. For vulnerabilities, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.
