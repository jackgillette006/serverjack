# serverjack

Your tmux sessions and coding agents, from your phone. One Python file, no
Node, no sudo.

[Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [MIT license](LICENSE)

serverjack is a web front door to a home server, meant to be reached over
Tailscale from an iPhone or a laptop. Open a URL and you get three things:

- **Run a command** — a paste box at the top. An agent tells you to run
  something it can't (`sudo apt install ...`, a service restart, a disk
  check): paste it, tap Run, and you land in a real terminal with it running.
- **Sessions** — every tmux session on the box as a button. Tap to attach.
  Any "type a path" field accepts a directory that doesn't exist yet and
  creates it, so starting a shell or an agent in a new project is one step.
  Open, rename, kill, pop out into its own window on a desktop, or hand off to
  a real SSH client. A "New shell" form for starting one in a chosen directory.
- **Agents** — a collapsed accordion row per coding CLI (Claude Code, Codex,
  OpenCode, GitHub Copilot CLI, Gemini CLI). Open one and it lists the ways to
  start that tool side by side, one line each on how they differ: install it,
  log in, open it in a directory, open it with remote control, or start its
  remote-control server — each of those is a button that runs a
  command in a tmux session and shows you the terminal.

The terminal itself is [ttyd](https://github.com/tsl0922/ttyd) in an iframe,
with session tabs, a tmux-window picker on the active tab, a phone soft-key row
(Esc, Tab, Shift-Tab, Ctrl, arrows, ^C, PgUp/PgDn, Paste, Copy). Touch-and-hold
the terminal for the browser's own Paste callout.
"Add to Home Screen" on iOS gives a full-screen app with no browser chrome.

## Quick start

Requirements: Linux, systemd, tmux, Python 3.9+ and curl. Tailscale is optional
but recommended.

```sh
git clone https://github.com/jackgillette006/serverjack
bash serverjack/install.sh
```

Clone it anywhere you keep code. The installer records that path in the user
units and the built-in "Update serverjack" shortcut runs `git pull` there, so
leave the checkout where it is; move it and re-run `install.sh` if you must.

serverjack has no password of its own. Anyone who can reach it gets a shell as
the account running it. Keep it behind `tailscale serve` or a reverse proxy
with real authentication, never `tailscale funnel`. On a shared machine, use
`install.sh --unix`; set `SERVERJACK_ALLOW` when the tailnet has other users.
Read the full [security model](#security-model-read-this-first) before exposing
the service.

A light CRT costume runs over all of that: a ~320ms tube warm-up when a page
loads, a collapse-to-a-line when you leave through Close or open a session in
the same tab, a scanline sweep while the terminal is connecting, and a barely
visible flicker/roll on the landing page's background. It is CSS only (opacity
and transform, nothing that repaints), off under `prefers-reduced-motion`, and
never sits over the terminal once it is connected. The **CRT fx** control in the
landing-page footer (and at the bottom of the terminal's new-session panel)
toggles it instantly and remembers the choice; `SERVERJACK_FX=off` makes off the
default for everyone.

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

### Update serverjack

The Shortcuts list has one row you did not add: **Update serverjack**, marked
*built-in* and with no delete button. It runs

```
cd <the checkout this is running from> && git pull --ff-only && bash install.sh
```

in an ordinary command session called `update`, so you watch the pull and the
installer scroll past and are left at a prompt with the result. It only appears
when the copy of serverjack you are running really is a git checkout (there is
a `.git` next to `bin/`) — a tarball has nothing to pull.

`install.sh` restarts the serverjack unit at the end, which is fine from inside
the browser: the unit is `KillMode=process`, so the tmux server and this
session outlive the restart, and the page reconnects to the same session as
soon as the new process is listening.

## Sessions

Every tmux session on the box is a row: a status dot, the command, the
directory, how many windows, and how long it has been there. **Open** attaches
(a pop-out window on a desktop, the same tab on a phone). The ⋯ menu has
*Open here*, *Pop out*, the two SSH hand-offs, **Rename**, and *Kill session*.

Rename unfolds a small text box in place; the same rules as a new session
apply, so tmux's forbidden characters (`:` and `.`) and a name something else
already has are refused with the reason. Renaming a session leaves a browser
sitting on the old `/s/<name>` without a session. That is harmless: the page
notices within 15 seconds that the name is gone and moves itself to another session,
exactly as it does when a session is killed.

### tmux windows

The bar's tabs are *sessions*. Windows live inside a session, and when the one
you are looking at has more than one the active tab gains a small count badge
(`pwtest · 2/3`). Tapping the active tab opens a compact list of the windows —
index, name, and the command running in each, with the current one marked —
and tapping one selects it. With a single window the active tab does nothing,
as before.

Selecting a window is a tmux operation, not a browser one, so **every client
attached to that session moves with you** — the phone and the desktop are
looking at the same session. That is tmux, not serverjack.

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

### Start at boot

Every server and daemon option row has a small **start at boot** checkbox. Tick
it and the thing is recorded in `~/.config/serverjack/autostart.json`:

```json
[
  {"tool": "claude", "kind": "server", "dir": "/home/you/projects/app"},
  {"tool": "codex", "kind": "daemon"}
]
```

An entry means "make sure this is running when serverjack starts". Fifteen
seconds after startup (the unit waits for `network-online.target`, and these
commands all want the network; override with `SERVERJACK_AUTOSTART_DELAY`) a
background thread walks the list: a daemon whose pidfile names no live process
is started, and a server whose session is missing — or is sitting at a dead
shell — is created in its directory. Anything already up is left alone, and
every decision is logged to `journalctl --user -u serverjack`.

Stopping something from the page **removes** its entry, so a deliberate stop
does not come back after the next restart. Starting something does not add one
unless you tick the box.

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

**There is one listener, and the terminal is behind it.** serverjack serves
`/term/` itself: it reverse-proxies that path — WebSocket upgrade and all — to
ttyd on `$XDG_RUNTIME_DIR/serverjack/ttyd.sock`, a socket inside a `0700`
directory that no other account and no tailnet device can open. ttyd has no
notion of a user and cannot tell who is on the other end of its socket, so it
is never exposed; every check below runs before a single byte reaches it. The
runtime directory itself is verified at startup (a real directory, not a
symlink, owned by you, mode `0700`) and serverjack refuses to start otherwise —
the `/tmp/serverjack-$UID` fallback used when there is no `$XDG_RUNTIME_DIR`
lives in a world-writable place, so its parent is checked the same way.

**Other accounts on the same machine can't reach it.** A localhost TCP port
has no owner: on a box with two logins, `curl http://127.0.0.1:7680/run` would
otherwise hand the *other* account a shell as you. So serverjack looks every
connection up in `/proc/net/tcp` and answers only root (that's `tailscaled`
proxying for `tailscale serve`) and its own user — anyone else gets a plain
403, before routing, before `/healthz`, before `/term/`. A reverse proxy running
as its own user needs its worker uid in `SERVERJACK_TRUST_UIDS`;
`SERVERJACK_TRUST_LOCAL=1` turns the check off entirely, which hands every local
account a shell, so don't. (Only the exact words `1`, `yes`, `true` or `on`
count as on — a typo, or `false`, leaves the check running.)

`SERVERJACK_LISTEN=unix` is the alternative: serverjack binds a socket in
`$XDG_RUNTIME_DIR/serverjack` too, mode `0600` inside that `0700` directory,
and the kernel does the same job with no uid list to maintain. The catch is
that `tailscale serve` will not proxy to a Unix socket for an unprivileged
caller, so that mode costs a one-time `sudo`. tcp is the default because the
no-sudo install matters more — see the residual risk at the end of this
section.

**`SERVERJACK_ALLOW` restricts an instance to named tailnet logins.**
`tailscale serve` authenticates the tailnet *device*, not the person, so on a
shared tailnet every device that can reach the port gets that account's shell.
Set `SERVERJACK_ALLOW=alice@github` (comma-separated for more) and every
request — the terminal included, because serverjack serves that too — must
carry a matching `Tailscale-User-Login` header or it gets a 403 page. The page
deliberately does *not* name the allowed logins; it says only that this
serverjack belongs to someone else and who you are signed in as. Leave `ALLOW`
unset and there is no identity check: the tailnet is the trust boundary.

**That header is only believed from a peer that could have authenticated it.**
`Tailscale-User-Login` is read when the connection's owner is root (that is
`tailscaled`, and it is what `tailscale serve` sets the header from), or a uid
you list in `SERVERJACK_TRUST_IDENTITY_UIDS`. For every other allowed peer —
your own account, a proxy uid from `SERVERJACK_TRUST_UIDS` — the header is
treated as absent, because such a peer could simply have written it. Only add a
uid to `SERVERJACK_TRUST_IDENTITY_UIDS` for a proxy that authenticates the user
itself *and* strips any copy the client sent; `examples/nginx.conf` shows both
halves.

**Only known `Host:` values are answered.** A domain someone else controls can
be pointed at `127.0.0.1` and then loaded in your browser — DNS rebinding — and
the page would be same-origin with *their* name, free to read responses and
POST back. Nothing above stops that: the connection really does come from a
browser on this machine. So every request must name a host serverjack knows:
`127.0.0.1`, `localhost`, `[::1]` (any port), this machine's hostname, its
tailnet DNS name, and anything you add in `SERVERJACK_HOSTS`. Anything else
gets `421 unknown Host` before routing. Put your own domain in
`SERVERJACK_HOSTS` if you front this with a reverse proxy.

**Cross-site POSTs are refused**, by `Sec-Fetch-Site` when the browser sends it
and by comparing `Origin` to `Host` when it doesn't. A POST carrying *neither*
is refused as well — every browser sends one of them, so its absence means the
request did not come from a page on this site. A script that means it (curl, the
test suite) says `Sec-Fetch-Site: same-origin`.

Identity comes from Tailscale, never from a password serverjack made up. If
you front it with your own proxy instead, that proxy must set
`Tailscale-User-Login` itself and strip any copy the client sent.

### Residual risk

In **tcp mode**, `tailscale serve` proxies to `127.0.0.1:7680`, and that port
belongs to whoever binds it first. While serverjack is *not* running — a crash,
a restart, the gap after `systemctl --user stop` — another local account can
bind 7680 and receive everything `tailscale serve` sends to it, including the
terminal traffic and your `Tailscale-User-Login` header. The peer-uid check
cannot help: it protects the port serverjack holds, not a port it has lost.
`Restart=on-failure` keeps retrying, so in practice the window is `RestartSec`
(3 seconds) after a crash — but it is unbounded while the unit is deliberately
stopped.

**`SERVERJACK_LISTEN=unix` is immune to this**: the socket lives in a `0700`
directory, so no other account can create it in serverjack's place. On a
machine you share with anyone, run `install.sh --unix` and paste the one
`sudo tailscale serve` line it prints. On a single-user box, tcp is fine.

Every button on the page runs a command as your user. The Agent rows run
vendor install scripts from the internet; the exact command is shown before
it runs, and it is the same one the vendor's own docs tell you to paste.

## Install (no sudo)

Requirements: Linux, systemd, tmux, python3, curl. Tailscale optional.

```
git clone https://github.com/jackgillette006/serverjack
bash serverjack/install.sh
```

The installer downloads ttyd and fzf binaries into `~/.local/bin` — HTTPS
only, and verified against sha256 hashes **pinned in `install.sh` itself**, not
just against a checksum file fetched from the same host as the binary — writes
`~/.config/serverjack/env`, installs two **user** systemd units, starts them,
and publishes serverjack with `tailscale serve` on
`https://<machine>.<tailnet>.ts.net/`. That is a single mount, `/`: ttyd is not
published at all, because serverjack proxies the terminal to it.

Flags (all optional):

| Flag | Effect |
|---|---|
| `--no-serve` | skip the `tailscale serve` step entirely |
| `--tcp` | listen on `127.0.0.1` ports (the default) |
| `--unix` | listen on private Unix sockets instead — needs one `sudo tailscale serve` |
| `--port N` | serverjack's port (default `7680`); implies `--tcp` |
| `--https-port N` | HTTPS port `tailscale serve` publishes on: `443`, `8443` or `10000` (default `443`) |
| `--title NAME` | page / tab / PWA name (default the hostname) |

**Scrolling.** A finger swipe or a mouse wheel over the terminal scrolls the
tmux pane's history: the page asks serverjack, which puts the pane into
copy mode and moves it, leaving copy mode again at the bottom. Nothing in
your tmux config is touched, and a mouse drag still selects text. If a
session has `mouse on`, tmux gets the wheel directly instead.

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
bash install.sh --port 7690 --https-port 8443 --title serverjack-alice
```

- **Ports.** Both accounts default to 7680 (ttyd needs none — it is on a Unix
  socket in each account's own runtime dir, so those never collide). The first
  one to start wins, so the installer checks first, refuses, and prints a
  ready-to-paste command with a free port. The other account can't *use* your
  port anyway — the peer-uid check refuses it — but two processes still can't
  bind one port.
- **`tailscale serve` is machine-wide, not per-user.** Whoever runs it owns
  that (HTTPS port, path) pair for the whole machine. Each account needs one
  mount: the first takes `/` on 443; the second uses `--https-port 8443` and is reached at
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
people. With it, bob gets a 403 page — the terminal included, since serverjack
serves that itself. Per-port tailnet ACLs are worth adding on top, but they are
defence in depth, not the mechanism.

The test harness chooses unused loopback ports and an isolated tmux socket, so
concurrent runs do not share sessions or listeners.

### Upgrading an existing install

Re-running `install.sh` after a pull is always safe, and from this version on
it also **removes the old `/term` `tailscale serve` mount** if your machine
still has one: the terminal now goes through serverjack, so a mount pointing
straight at ttyd's port would be a way around every check. The installer says
so when it takes one down. `uninstall.sh` turns off the `/` mount (and that old
`/term` one, for installs that predate the change).

## Configure

`~/.config/serverjack/env`:

| Variable | Default | Meaning |
|---|---|---|
| `SERVERJACK_LISTEN` | `tcp` | How **serverjack** listens; ttyd is always on `$XDG_RUNTIME_DIR/serverjack/ttyd.sock` behind it. `tcp`: the port below on `127.0.0.1`, with connections from other local accounts refused by the peer-uid check. `unix`: `web.sock` in that same `0700` directory, mode `0600` — needs one `sudo tailscale serve`, and is immune to the port-stealing risk above |
| `SERVERJACK_TRUST_UIDS` | unset | extra uids allowed to connect in `tcp` mode, comma-separated. A reverse proxy running as its own user needs its **worker** uid here (101 on `nginx:alpine`, 33 for Debian `www-data`) |
| `SERVERJACK_TRUST_LOCAL` | unset | `1` (or `yes`/`true`/`on`; nothing else) disables the peer-uid check. Only if you know why — it gives every local account a shell as you |
| `SERVERJACK_TRUST_IDENTITY_UIDS` | unset (root only) | extra uids whose `Tailscale-User-Login` header is believed. root (tailscaled) always is; every other peer's copy of that header is ignored. Only for a proxy that authenticates the user itself and strips the client's copy |
| `SERVERJACK_ALLOW` | unset | comma-separated tailnet logins (`alice@github`) allowed in. Unset = no identity check. Set = 403 for anyone else, terminal included |
| `SERVERJACK_HOSTS` | unset | extra `Host:` values to answer to, comma-separated (`term.example.com`). `127.0.0.1`, `localhost`, `[::1]`, the hostname and the tailnet DNS name are always accepted; anything else gets `421` |
| `SERVERJACK_PORT` | `7680` | serverjack's port (localhost) — `tcp` mode only |
| `SERVERJACK_HTTPS_PORT` | `443` | HTTPS port `tailscale serve` publishes on, and the only one `uninstall.sh` turns off — `443`, `8443` or `10000`. Give a second account on the machine its own |
| `SERVERJACK_TITLE` | hostname | page title, tab title, PWA name |
| `SERVERJACK_DIRS` | `~/projects:~/src:~/code:~` | directories offered when starting a session |
| `SERVERJACK_TOOLS` | unset (all) | optional comma-separated tool ids: restricts and orders the Agent rows, e.g. `claude,codex` |
| `SERVERJACK_TERM` | `/term/` | URL path serverjack serves the terminal on (proxying it to ttyd's socket) |
| `TTYD_EXTRA_ARGS` | unset | optional ttyd client options, shell-parsed as data with no expansion. Allowed flags: `-t`/`--client-option`, `-T`/`--terminal-type`, `-m`/`--max-clients`, and `-P`/`--ping-interval`. Listener, auth, command, base-path, origin and write-access flags are refused |
| `SERVERJACK_TMUX_STATUS` | `off` | sessions opened from the page get tmux's status line turned off (the bar shows tabs and window count instead); `on` leaves tmux alone |
| `SERVERJACK_SSH` | `auto` | `user@host` for the SSH menu items (tailnet DNS name if Tailscale is up, else hostname); `off` hides them |
| `SERVERJACK_FX` | unset (on) | `off` (or `0`/`no`/`false`) turns the CRT effects off by default; each browser can still flip them with the **CRT fx** toggle |
| `SERVERJACK_CONFIG` | `~/.config/serverjack` | config directory override |
| `SERVERJACK_AUTOSTART_DELAY` | `15` | seconds after startup before `autostart.json` is acted on |

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

## Status line and /api/status

Under the tagline is one quiet line of machine state:

```
load 0.42 · mem 61% · 1.2 TB free · up 12d 4h
```

straight from `os.getloadavg()`, `/proc/meminfo`, `shutil.disk_usage($HOME)`
and `/proc/uptime`. No caching, no background thread; anything the platform
doesn't answer is simply left out.

The same numbers, plus what the agents are doing, come out of `GET
/api/status` as JSON:

```json
{
  "sessions": 6, "attached": 1,
  "agents": [{"id": "claude", "installed": true,
              "servers_running": 1, "daemon_running": false}],
  "agents_summary": "1 server · 1 daemon",
  "load": [0.42, 0.5, 0.6], "mem_used_pct": 61,
  "disk_free_gb": 1204.3, "uptime_s": 1051200, "version": "1.1"
}
```

**Counts only.** No session names, no directories, not even the agents'
labels: a dashboard should say how busy the box is, not what you called things
or where they run. This is the one route `SERVERJACK_ALLOW` cannot check an
identity on, so it is kept to numbers.

`/api/status` is exempt from `SERVERJACK_ALLOW`, for the same reason
`/healthz` is: a dashboard tile polling it is a machine, not a tailnet user, so
there is no `Tailscale-User-Login` header to match and the check could only
ever 403 it. It is **not** exempt from the peer-uid check — only root
(tailscaled), you, and any uid in `SERVERJACK_TRUST_UIDS` can open the socket
at all.

A [Homepage](https://gethomepage.dev) tile, for example — the widget's `url`
must be one the dashboard's container can reach, so use the tailnet name if
that is how it is published:

```yaml
- serverjack:
    icon: mdi-console
    href: https://myhost.my-tailnet.ts.net/
    # Quoted: an unquoted colon in a value breaks Homepage's YAML.
    description: "Jack into your server: tmux sessions, a paste-and-run box, coding agents"
    widget:
      type: customapi
      url: https://myhost.my-tailnet.ts.net/api/status
      refreshInterval: 30000
      mappings:
        - field: sessions
          label: Sessions
          format: number
        - field: attached
          label: Attached
          format: number
        - field: agents_summary
          label: Agents
          format: text
```

## How it fits together

```
browser ──HTTPS──▶ tailscale serve ── / ──▶ 127.0.0.1:7680  bin/serverjack
                                              │   the page, the JSON API, and
                                              │   /term/ reverse-proxied to:
                                              └─▶ $XDG_RUNTIME_DIR/serverjack/ttyd.sock  ttyd
                                                    └─▶ bin/tmux-attach.sh <session> ──▶ tmux attach
```

**One `tailscale serve` mount, `/`.** ttyd is never published: it listens only
on that Unix socket, inside a `0700` directory, and serverjack forwards
everything under `SERVERJACK_TERM` to it — request line with the prefix
stripped, headers verbatim (so ttyd's own origin check still sees the real
`Host` and `Origin`), then raw bytes in both directions once the WebSocket
upgrade succeeds. If ttyd is down you get a 502 page saying so, in the frame.

(In `SERVERJACK_LISTEN=unix` mode serverjack's own backend is
`$XDG_RUNTIME_DIR/serverjack/web.sock` instead of the port.)

Both services run as you and talk to your normal tmux server, so the sessions
shown are the same ones `tmux ls` shows in any other login — including the
ones an Install or Run button started. Opening a session loads `/s/<name>`,
whose bar sits over an iframe of `/term/?arg=<name>`; ttyd passes that one
argument to `tmux-attach.sh`, which attaches. There is no no-argument fallback,
so `bin/tmux-picker.sh` is only for use from a real terminal.

The units use `KillMode=process` on purpose: if the browser is the first thing
to create a tmux session after boot, the tmux server is a child of the unit,
and a default restart would take every session down with it.

## Tests

`tests/run.sh` runs real browsers (Chromium, Firefox, WebKit with iPhone
emulation) in a Playwright container straight against serverjack — no proxy in
the middle any more, since serverjack serves the terminal itself — and reads the
tmux pane from the host to prove keystrokes arrived. It starts two instances on
scratch ports, each with its own scratch runtime dir (and so its own
`ttyd.sock`), so docker is the only thing that has to be installed and a real
install is never touched. One of the suites (`pwauth`) drives the instance with
`SERVERJACK_ALLOW` set, plays the part of `tailscale serve` by sending the
identity header, and proves the terminal is behind that check — both a page
fetch and a raw WebSocket handshake to `/term/ws` are refused without it.
Host-side checks prove the peer-uid rule by curling from containers running as
uid 65534, 0 and 101 (including `/term/`), that an unknown `Host:` gets 421, and
that the terminal's WebSocket accepts a same-origin and refuses a foreign
origin through the proxy; another starts a throwaway instance with an
`autostart.json` pointing at a fake server to prove it comes up on its own. `docs/MANUAL-TESTS.md` is a
checklist for real devices; iOS Safari's soft-keyboard behaviour is only
verifiable there.

## Known limitations

- Linux WebKit browsers (Epiphany) still need Ctrl+Shift+C to copy.
- While scrolled back, the pane is in tmux copy mode: keys go to copy mode
  until you scroll to the bottom or press Esc/`q`. That's tmux.
- tmux resizes a session to its most recent client, so a phone attaching
  shrinks the desktop view until the desktop sends a key. That's tmux.
- Installer and units are Linux + systemd only.

## License

MIT. See [LICENSE](LICENSE).
