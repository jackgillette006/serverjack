# serverjack

Your tmux sessions and coding agents, from your phone. One Python file, no
Node, no sudo.

serverjack is a web front door to a home server, meant to be reached over
Tailscale from an iPhone or a laptop. Open a URL and you get three things:

- **Run a command** — a paste box at the top. An agent tells you to run
  something it can't (`sudo apt install ...`, a service restart, a disk
  check): paste it, tap Run, and you land in a real terminal with it running.
- **Sessions** — every tmux session on the box as a button. Tap to attach.
  Any "type a path" field accepts a directory that doesn't exist yet and
  creates it, so starting a shell or an agent in a new project is one step.
  Open, kill, pop out into its own window on a desktop, or hand off to a real
  SSH client. A "New shell" form for starting one in a chosen directory.
- **Agents** — a collapsed accordion row per coding CLI (Claude Code, Codex,
  OpenCode, GitHub Copilot CLI, Gemini CLI). Open one and it lists the ways to
  start that tool side by side, one line each on how they differ: install it,
  log in, open it in a directory, open it with remote control, or start its
  remote-control server — each of those is a button that runs a
  command in a tmux session and shows you the terminal.

The terminal itself is [ttyd](https://github.com/tsl0922/ttyd) in an iframe,
with session tabs, a phone soft-key row (Esc, Tab, Shift-Tab, Ctrl, arrows,
^C, PgUp/PgDn, Paste, Copy) and a compose bar you can type or dictate into.
"Add to Home Screen" on iOS gives a full-screen app with no browser chrome.

Everything server-side is one stdlib Python file plus a prebuilt ttyd binary.
No pip, no npm, no compiler, no root.

## Screenshots

| Landing page | Terminal | Desktop |
|---|---|---|
| ![Landing page on iPhone](docs/shots/iphone-landing.png) | ![Terminal on iPhone](docs/shots/iphone-term.png) | ![Landing page on a desktop](docs/shots/desktop.png) |

## Run a command

This is the reason serverjack exists. Coding agents can do almost everything
now except the things that need a password, a device, or a human at the
machine. When one stops and says "run this yourself", you are usually away
from the server with a phone in your hand.

Paste the command into the box and tap Run. serverjack starts a new tmux
session, runs the command **in front of a login shell**, and drops you into
the terminal. So:

- an interactive `sudo` prompt appears and you can type the password;
- anything that asks a question (apt, a login flow, a confirmation) works;
- when the command finishes the session stays open at a shell prompt, so you
  can see the output and keep going instead of watching a session vanish.

Tick "save as a shortcut" and it becomes a one-tap button in the Shortcuts
list for next time. Shortcuts live in `~/.config/serverjack/shortcuts.json`.

## Agents

The agents are an **accordion**: one collapsed row per tool, so five tools
take about the height of one card. The row itself is the summary — tool name,
state, and a pill for any server or daemon that is up — and tapping it opens
the body while closing whichever row was open (native `<details name="agent">`,
no JavaScript). serverjack never parses the tool's output; every button just
launches a command in a tmux session and shows you the terminal.

A row is in one of three states:

1. **Not installed** — an Install button. It shows the exact command first,
   then runs the vendor's official installer in a visible terminal.
2. **Installed, not logged in** — a Log in button. These flows print a URL or
   a device code, which is fine to read and tap in a phone browser.
3. **Ready** — the directory picker once at the top, then one **option row**
   per way of starting the tool: its label, a one-line note on how it differs
   from the others, and the button. They end with a quiet
   "Log in / switch account".

Ready-state options, per tool:

| Tool | Open | Remote control | Server / daemon |
|---|---|---|---|
| Claude Code | `claude` — interactive Claude Code in this terminal only | **Open with remote control**: `claude --remote-control`, the same interactive session, also steerable from the Claude app and claude.ai/code | **Remote Control server**: `claude remote-control` in tmux session `claude-remote`, started in the directory you pick. No local chat — the Claude app starts sessions here on demand, several at once. One server per project directory; prints a QR code, gives up after ~10 minutes without network |
| Codex | `codex` — interactive Codex in this terminal only | **Pair with phone**: `codex remote-control pair`, prints a short-lived pairing code | **Remote control daemon**: `codex remote-control start` / `stop` (status from `~/.codex/app-server-daemon/app-server.pid`). The ChatGPT app connects to it and opens Codex sessions in any directory on this machine |
| OpenCode | `opencode` — interactive TUI in this terminal | — | **Server for the mobile app**: `opencode serve` in tmux session `opencode-serve`. Binds 127.0.0.1:4096 by default; override `cmd` in `tools.json` to reach it over Tailscale |
| GitHub Copilot CLI | `copilot` — interactive Copilot in this terminal only | **Open with remote control**: `copilot --remote`, same session, also steerable from GitHub Mobile or github.com | — |
| Gemini CLI | `gemini` — interactive Gemini CLI in this terminal | — | — |

Install and login commands: Claude Code
`curl -fsSL https://claude.ai/install.sh | bash` / `claude auth login`; Codex
`curl -fsSL https://chatgpt.com/codex/install.sh | sh` / `codex login`;
OpenCode `curl -fsSL https://opencode.ai/install | bash` /
`opencode auth login`; Copilot `curl -fsSL https://gh.io/copilot-install | bash`
then `/login` at its prompt; Gemini `npm install -g @google/gemini-cli`, which
signs you in on first run.

Claude Code and Codex install as single binaries and do not need Node. Gemini
CLI does; if Node isn't on the box, its row says so instead of offering a
button that would fail.

Coding CLIs like to install into a private bin directory that only your
`.bashrc` adds to `PATH`, which a systemd unit never reads. Each built-in tool
therefore lists the directories it might live in (`paths`); the ones that
exist are added to the `PATH` used for the installed/logged-in checks, the
daemon commands, and every session serverjack starts.

## Why this and not X

**Claude Code Remote Control, Codex remote control in the ChatGPT app, GitHub
Copilot CLI remote control, OpenCode's server plus mobile app** — use them.
They are better at driving an agent from a phone than a web terminal will ever
be, and serverjack deliberately does not compete: no agent status, no
notifications, no chat UI. They handle the agent; serverjack handles the
server. It gets those daemons installed, logged in and running in the first
place, and gives you a real terminal for everything that isn't an agent —
docker, systemd, logs, disks, the `sudo` prompt the agent can't answer.

**[VibeTunnel](https://github.com/amantus-ai/vibetunnel), agentboard, Codeman**
— genuinely good, and if you already run Node on the box, look at them. They
need Node or Bun and compile `node-pty`, which is a real dependency chain on a
minimal home server. serverjack is a Python file and a downloaded binary.

**Plain ttyd** — serverjack is ttyd plus the parts ttyd doesn't have: a
session list, a launcher, phone keys, and a page that survives a screen lock.

**Zellij's built-in web client** — nice, but only for Zellij. tmux has no
equivalent, and most servers already have tmux sessions in them.

## Security model, read this first

serverjack has **no authentication of its own**. Anyone who can reach it gets
a shell as the user it runs as. It binds `127.0.0.1` only and is meant to be
published by something that authenticates:

- **`tailscale serve`** (what `install.sh` sets up): only devices on your
  tailnet, subject to your ACLs. Never `tailscale funnel` it.
- Or a reverse proxy with real auth in front (VPN-only, mTLS, SSO). See
  `examples/nginx.conf`.

Treat the URL exactly like SSH access. The app refuses cross-site POSTs and
ttyd rejects WebSockets from other origins, so a malicious web page can't
drive it from a logged-in browser, but that's hardening, not auth.

Every button on the page runs a command as your user. The Agent rows run
vendor install scripts from the internet; the exact command is shown before
it runs, and it is the same one the vendor's own docs tell you to paste.

## Install (no sudo)

Requirements: Linux, systemd, tmux, python3, curl. Tailscale optional.

```
git clone https://github.com/jackgillette006/serverjack ~/projects/serverjack
bash ~/projects/serverjack/install.sh
```

The installer downloads pinned, checksum-verified ttyd and fzf binaries into
`~/.local/bin`, writes `~/.config/serverjack/env`, installs two **user**
systemd units, starts them, and publishes them with `tailscale serve` on
`https://<machine>.<tailnet>.ts.net/`.

Two things need root **once per machine**. The installer detects and prints
them rather than prompting for a password:

```
sudo loginctl enable-linger $USER     # user units start at boot
sudo tailscale set --operator=$USER   # tailscale serve without sudo
```

Then re-run `install.sh`. From here on, nothing needs sudo:

```
systemctl --user restart serverjack serverjack-ttyd   # after editing bin/ or the env file
journalctl --user -u serverjack -f
bash install.sh                                       # re-run after git pull (idempotent)
bash uninstall.sh
```

### Upgrading from tmux-web

This project used to be called tmux-web. Just pull and re-run `install.sh`: if
`~/.config/serverjack/env` doesn't exist yet it converts the old
`~/.config/tmux-web/env` (renaming `TMUX_WEB_*` to `SERVERJACK_*` and replacing
the old `TMUX_WEB_TOOLS` line with a pointer to the new tools registry), copies
`shortcuts.json` across, and stops and removes the old `tmux-web` and `ttyd`
user units so the ports are free for the new ones. The old config directory is
left in place; delete it when you're happy.

## Configure

`~/.config/serverjack/env`:

| Variable | Default | Meaning |
|---|---|---|
| `SERVERJACK_PORT` | `7680` | landing page port (localhost) |
| `TTYD_PORT` | `7681` | ttyd port (localhost) |
| `SERVERJACK_TITLE` | hostname | page title, tab title, PWA name |
| `SERVERJACK_DIRS` | `~/projects:~/src:~/workspace:~` | directories offered when starting a session |
| `SERVERJACK_TOOLS` | unset (all) | optional comma-separated tool ids: restricts and orders the Agent rows, e.g. `claude,codex` |
| `SERVERJACK_TERM` | `/term/` | URL path your proxy mounts ttyd on |
| `TTYD_EXTRA_ARGS` | | e.g. `-b /term` if your proxy does not strip the prefix |
| `SERVERJACK_SSH` | `auto` | `user@host` for the SSH menu items (tailnet DNS name if Tailscale is up, else hostname); `off` hides them |
| `SERVERJACK_CONFIG` | `~/.config/serverjack` | config directory override |

### Tools

The Agent rows come from a registry: the built-ins above, plus
`~/.config/serverjack/tools.json` if it exists. That file is a JSON **list of
objects**, merged over the built-ins by `id` — a partial object overrides just
the fields it names, `"hidden": true` removes a built-in row, and an
unrecognised `id` is appended as a new tool.

| Field | Meaning |
|---|---|
| `id` | key used for merging and for `SERVERJACK_TOOLS` |
| `label` | name shown in the row |
| `bin` | executable to look for; missing means "not installed" |
| `docs` | URL shown at the end of the row |
| `install` | shell command run by the Install button |
| `install_note` | text shown next to it |
| `needs` | `"node"` — the row explains the prerequisite if it's missing |
| `login` | shell command run by the Log in button |
| `login_note` | text shown next to it |
| `login_check` | command whose exit status 0 means "logged in" |
| `run` | interactive command for the "Open" option |
| `run_note` | one-line note under the Open option — how it differs from the others |
| `paths` | extra directories (may use `~`) to look for `bin` in, on top of `PATH` |
| `server` | `{label, cmd, session, note}` — long-running command kept in a named tmux session |
| `daemon` | `{label, start, stop, pidfile, note}` — self-daemonizing command with start/stop and a pidfile for status |
| `actions` | list of `{label, cmd, note, dir}` extra option rows; `note` is the one-liner beside it, `"dir": true` gives it the directory picker |

Example — point OpenCode's server at a different port and hide the Gemini row:

```json
[
  {
    "id": "opencode",
    "server": {
      "label": "OpenCode server",
      "cmd": "opencode serve --port 4096",
      "session": "opencode-serve",
      "note": "Pair the OpenCode mobile app with this machine's tailnet name, port 4096."
    }
  },
  { "id": "gemini", "hidden": true }
]
```

A tool session runs the tool in front of a login shell, so if it isn't
installed or isn't logged in you land on its error message and a prompt
instead of a session that vanished. Shells with a start command, the Run box,
and shortcuts all work the same way: the command runs, then you get a prompt.

## How it fits together

```
browser ──HTTPS──▶ tailscale serve ──┬── /       ──▶ 127.0.0.1:7680  bin/serverjack   (page, JSON API)
                                     └── /term/  ──▶ 127.0.0.1:7681  ttyd ──▶ bin/tmux-attach.sh <session>
                                                                                    └─▶ tmux attach
```

Both services run as you and talk to your normal tmux server, so the sessions
shown are the same ones `tmux ls` shows in any other login — including the
ones an Install or Run button started. Opening a session loads `/s/<name>`,
whose bar sits over an iframe of `/term/?arg=<name>`; ttyd passes the argument
to `tmux-attach.sh`, which attaches. If ttyd is opened without an argument it
falls back to an fzf picker.

The units use `KillMode=process` on purpose: if the browser is the first thing
to create a tmux session after boot, the tmux server is a child of the unit,
and a default restart would take every session down with it.

## Tests

`tests/run.sh` runs real browsers (Chromium, Firefox, WebKit with iPhone
emulation) in a Playwright container against a local nginx that mimics
tailscale serve's routing, and reads the tmux pane from the host to prove
keystrokes arrived. Needs docker and a running ttyd. `docs/MANUAL-TESTS.md`
is a checklist for real devices; iOS Safari's soft-keyboard behaviour is only
verifiable there.

## Known limitations

- Linux WebKit browsers (Epiphany) still need Ctrl+Shift+C to copy.
- tmux resizes a session to its most recent client, so a phone attaching
  shrinks the desktop view until the desktop sends a key. That's tmux.
- Scrolling history on a phone needs `set -g mouse on` in `~/.tmux.conf`
  (or the PgUp/PgDn soft keys, which enter tmux copy mode).
- Installer and units are Linux + systemd only.

## License

MIT.
