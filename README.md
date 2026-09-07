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
| Claude Code | `claude` — interactive Claude Code in this terminal only | **Open with remote control**: `claude --remote-control`, the same interactive session, also steerable from the Claude app and claude.ai/code | **Remote Control server**: `claude remote-control`, started in the directory you pick, in a tmux session named `claude-remote-<dir>`. No local chat — the Claude app starts sessions here on demand, several at once. One server per project directory, so the row lists every running one with its directory and Start adds another; prints a QR code, gives up after ~10 minutes without network |
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

serverjack has **no password of its own**. Anyone who can reach it gets a
shell as the user it runs as. It is meant to be published by something that
authenticates:

- **`tailscale serve`** (what `install.sh` sets up): only devices on your
  tailnet, subject to your ACLs. Never `tailscale funnel` it.
- Or a reverse proxy with real auth in front (VPN-only, mTLS, SSO). See
  `examples/nginx.conf`.

Treat the URL exactly like SSH access. The app refuses cross-site POSTs and
ttyd rejects WebSockets from other origins, so a malicious web page can't
drive it from a logged-in browser, but that's hardening, not auth.

**Other accounts on the same machine can't reach it.** A localhost TCP port
has no owner: on a box with two logins, `curl http://127.0.0.1:7680/run` would
otherwise hand the *other* account a shell as you. So serverjack looks every
connection up in `/proc/net/tcp` and answers only root (that's `tailscaled`
proxying for `tailscale serve`) and its own user — anyone else gets a plain
403, before routing, before `/healthz`. A reverse proxy running as its own user
needs its worker uid in `SERVERJACK_TRUST_UIDS`; `SERVERJACK_TRUST_LOCAL=1`
turns the check off entirely, which hands every local account a shell, so
don't. ttyd has no such check, and doesn't need one: `bin/tmux-attach.sh`
refuses to attach without a session token, and only the page can mint those.

`SERVERJACK_LISTEN=unix` is the alternative: both services bind sockets in
`$XDG_RUNTIME_DIR/serverjack`, mode `0600` inside a `0700` directory, and the
kernel does the same job with no uid list to maintain. The catch is that
`tailscale serve` will not proxy to a Unix socket for an unprivileged caller,
so that mode costs a one-time `sudo`. tcp is the default because the no-sudo
install matters more.

**`SERVERJACK_ALLOW` restricts an instance to named tailnet logins.**
`tailscale serve` authenticates the tailnet *device*, not the person, so on a
shared tailnet every device that can reach the port gets that account's shell.
Set `SERVERJACK_ALLOW=alice@github` (comma-separated for more) and every
request must carry a matching `Tailscale-User-Login` header — the one
`tailscale serve` injects — or it gets a 403 page naming who the instance
belongs to. That header is trustworthy in both listen modes, because the checks
above mean nothing but tailscaled and you can open a connection in the first
place. Leave `ALLOW` unset and there is no identity check: the tailnet is the
trust boundary, as before.

**The terminal is token-gated, always.** `/term/?arg=<name>` only attaches when
the URL also carries that session's token — an HMAC over the session name,
keyed by a per-account secret in the runtime dir, minted by the page and
verified by `bin/tmux-attach.sh`. Without it, ttyd would be the way around
both of the checks above: it cannot tell a browser the page sent from one
that typed its URL. There is no no-argument fallback any more (`tmux-picker.sh`
is still in the repo for use from a real terminal).

Identity comes from Tailscale, never from a password serverjack made up. If
you front it with your own proxy instead, that proxy must set
`Tailscale-User-Login` itself and strip any copy the client sent.

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

Flags (all optional):

| Flag | Effect |
|---|---|
| `--no-serve` | skip the `tailscale serve` step entirely |
| `--tcp` | listen on `127.0.0.1` ports (the default) |
| `--unix` | listen on private Unix sockets instead — needs one `sudo tailscale serve` |
| `--port N` | landing page port (default `7680`); implies `--tcp` |
| `--ttyd-port N` | ttyd port (default `7681`); implies `--tcp` |
| `--https-port N` | HTTPS port `tailscale serve` publishes on: `443`, `8443` or `10000` (default `443`) |
| `--title NAME` | page / tab / PWA name (default the hostname) |

The value flags write into `~/.config/serverjack/env` — they set the
initial value when the file is created, and rewrite just that line if you pass
one later. Everything else in the file is left alone, so editing the file by
hand and passing flags are interchangeable.

Two things need root **once per machine**. The installer detects and prints
them rather than prompting for a password:

```
sudo loginctl enable-linger $USER     # user units start at boot
sudo tailscale set --operator=$USER   # tailscale serve without sudo
```

`--unix` adds a third, which is why it is not the default: tailscale will not
proxy to a Unix socket for an unprivileged caller, even the operator —

```
401 Unauthorized: must be root, or be an operator and able to run
'sudo tailscale' to serve a path or Unix socket
```

— so in that mode the installer prints two `sudo tailscale serve … unix:…`
lines for you to paste. Serve config is persistent, so it is still once per
machine.

Then re-run `install.sh`. From here on, nothing needs sudo:

```
systemctl --user restart serverjack serverjack-ttyd   # after editing bin/ or the env file
journalctl --user -u serverjack -f
bash install.sh                                       # re-run after git pull (idempotent)
bash uninstall.sh
```

### Two accounts on one machine

serverjack is per-user by design: user systemd units, your own tmux server,
your own config, and each account sees **only its own** tmux sessions. Nothing
here needs sudo beyond the operator grant, and that is only for whoever
publishes. The second account installs with its own ports, HTTPS port and name:

```
bash install.sh --port 7690 --ttyd-port 7691 --https-port 8443 --title serverjack-alice
```

- **Ports.** Both accounts default to 7680/7681. The first one to start wins,
  so the installer checks first, refuses, and prints a ready-to-paste command
  with free ports. The other account can't *use* your port anyway — the
  peer-uid check refuses it — but two processes still can't bind one port.
- **`tailscale serve` is machine-wide, not per-user.** Whoever runs it owns
  that (HTTPS port, path) pair for the whole machine. The first account takes
  `/` and `/term` on 443; the second uses `--https-port 8443` and is reached at
  `https://<machine>.<tailnet>.ts.net:8443/` (10000 is the third and last port
  tailscale will terminate TLS on). The installer will not overwrite a mount
  that points at someone else's backend — it prints the remedy and skips serve.
  `uninstall.sh` only turns off the HTTPS port recorded in *its own*
  `SERVERJACK_HTTPS_PORT`, so it can't unpublish the other account.
- **The operator grant is *not* per user.** `tailscale set --operator=` takes a
  single Unix username for the whole machine, so only one account can run
  `tailscale serve` without sudo. Either that account runs the serve commands
  for both (the other installs with `--no-serve`), or the second account's
  install has sudo available; the installer says which case it hit.
- **`--title`.** Both accounts default the title to the hostname, so on a phone
  the two pages, tab titles and home-screen icons are indistinguishable. Give
  each account its own (`--title serverjack-alice`).
- `loginctl enable-linger` **is** per user: each account needs its own, or its
  units only run while it is logged in.

**Set `SERVERJACK_ALLOW` in each account's env file to that account's own
tailnet login.** Without it, `tailscale serve` will happily hand *any* tailnet
device that opens `:8443` a shell as alice — serve authenticates devices, not
people. With it, bob gets a 403 page, and the terminal refuses him too because
he has no token. Per-port tailnet ACLs are worth adding on top, but they are
defence in depth, not the mechanism.

Don't run `tests/run.sh` from two accounts at once: it uses fixed scratch ports
(7690-7693, 7698, 7699) and the second run will fail on the busy port.

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
| `SERVERJACK_LISTEN` | `tcp` | `tcp`: the two ports below on `127.0.0.1`, with connections from other local accounts refused by the peer-uid check. `unix`: sockets in `$XDG_RUNTIME_DIR/serverjack` (`web.sock`, `ttyd.sock`) instead, `0600` in a `0700` directory — needs one `sudo tailscale serve` |
| `SERVERJACK_TRUST_UIDS` | unset | extra uids allowed to connect in `tcp` mode, comma-separated. A reverse proxy running as its own user needs its **worker** uid here (101 on `nginx:alpine`, 33 for Debian `www-data`) |
| `SERVERJACK_TRUST_LOCAL` | unset | `1` disables the peer-uid check. Only if you know why — it gives every local account a shell as you |
| `SERVERJACK_ALLOW` | unset | comma-separated tailnet logins (`alice@github`) allowed in. Unset = no identity check. Set = 403 for anyone else, and the terminal requires the page's signed token |
| `SERVERJACK_PORT` | `7680` | landing page port (localhost) — `tcp` mode only |
| `TTYD_PORT` | `7681` | ttyd port (localhost) — `tcp` mode only |
| `SERVERJACK_HTTPS_PORT` | `443` | HTTPS port `tailscale serve` publishes on, and the only one `uninstall.sh` turns off — `443`, `8443` or `10000`. Give a second account on the machine its own |
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
| `server` | `{label, cmd, session, note, per_dir}` — long-running command kept in a named tmux session; `per_dir: true` means one per project directory, sessions named `<session>-<dir>`, each listed with its directory |
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
browser ──HTTPS──▶ tailscale serve ──┬── /      ──▶ 127.0.0.1:7680  bin/serverjack (page, JSON API)
                                     └── /term/ ──▶ 127.0.0.1:7681  ttyd
                                                     └─▶ bin/tmux-attach.sh <session> <token> ──▶ tmux attach
```

(In `SERVERJACK_LISTEN=unix` mode the two backends are
`$XDG_RUNTIME_DIR/serverjack/web.sock` and `ttyd.sock` instead.)

Both services run as you and talk to your normal tmux server, so the sessions
shown are the same ones `tmux ls` shows in any other login — including the
ones an Install or Run button started. Opening a session loads `/s/<name>`,
whose bar sits over an iframe of `/term/?arg=<name>&arg=<token>`; ttyd passes
both arguments to `tmux-attach.sh`, which verifies the token and attaches. A
missing or wrong token is always refused — there is no fallback, so
`bin/tmux-picker.sh` is now only for use from a real terminal.

The units use `KillMode=process` on purpose: if the browser is the first thing
to create a tmux session after boot, the tmux server is a child of the unit,
and a default restart would take every session down with it.

## Tests

`tests/run.sh` runs real browsers (Chromium, Firefox, WebKit with iPhone
emulation) in a Playwright container against a local nginx that mimics
tailscale serve's routing, and reads the tmux pane from the host to prove
keystrokes arrived. It starts its own serverjack and ttyd on scratch ports
with a scratch runtime dir, so docker is the only thing that has to be
installed and a real install is never touched. One of the suites (`pwauth`)
brings up a second pair with `SERVERJACK_ALLOW` set and plays the part of
`tailscale serve` by sending the identity header; a host-side check proves the
peer-uid rule by curling from containers running as uid 65534, 0 and 101. `docs/MANUAL-TESTS.md` is a
checklist for real devices; iOS Safari's soft-keyboard behaviour is only
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
