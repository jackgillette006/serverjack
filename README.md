# tmux-web

A phone-friendly web front end for your tmux sessions. Open a URL, see your
sessions as buttons, tap one, and you're in it. Start a shell, a Claude Code
session, or a Codex session in a chosen directory from the same page. Built
for reaching a home server over Tailscale from a laptop or an iPhone.

- **Landing page**: sessions with Open/kill buttons; **shortcuts** (your own
  one-tap commands, added and removed in the page); a form for new sessions.
  A shell needs no name or directory and can start with a pasted command;
  a coding tool (Claude Code, Codex, ... configurable) takes a name and a
  directory.
- **In a session**: a slim bar with session tabs, `+` new, `✕` kill, `↗` pop-out
  into a chrome-less window.
- **Built for phones**: a soft-key row (Esc, Tab, ⇧Tab, Ctrl, arrows, ^C,
  PgUp/PgDn, Paste, Copy) and a chat-style **compose bar**: type or dictate with
  your normal keyboard, Send pastes it into the terminal and presses Enter.
  Touch-and-hold on the terminal brings up the native Paste callout. **Copy**
  shows the screen as plain text: tap a line to copy it, or select normally.
- **Clipboard that behaves on desktop**: Ctrl+C copies when there's a
  selection and interrupts otherwise; Ctrl+V pastes. Mac keeps native Cmd+C/V.
- **Survives phones**: the WebSocket re-attaches after a screen lock; if the
  session you're in exits, you're moved to another one.
- **Add to Home Screen** on iOS gives a full-screen app with no browser chrome.
- **No dependencies**: one stdlib Python file plus [ttyd](https://github.com/tsl0922/ttyd)
  for the terminal itself. No pip, no node, no root.

## Security model, read this first

tmux-web has **no authentication of its own**. Anyone who can reach it gets a
shell as the user it runs as. It binds `127.0.0.1` only and is meant to be
published by something that authenticates:

- **`tailscale serve`** (what `install.sh` sets up): only devices on your
  tailnet, subject to your ACLs. Never `tailscale funnel` it.
- Or a reverse proxy with real auth in front (VPN-only, mTLS, SSO). See
  `examples/nginx.conf`.

Treat the URL exactly like SSH access. The app refuses cross-site POSTs and
ttyd rejects WebSockets from other origins, so a malicious web page can't
drive it from a logged-in browser, but that's hardening, not auth.

## Install (no sudo)

Requirements: Linux, systemd, tmux, python3, curl. Tailscale optional.

```
git clone https://github.com/YOURNAME/tmux-web ~/projects/tmux-web
bash ~/projects/tmux-web/install.sh
```

The installer downloads pinned, checksum-verified ttyd and fzf binaries into
`~/.local/bin`, writes `~/.config/tmux-web/env`, installs two **user** systemd
units, starts them, and publishes them with `tailscale serve` on
`https://<machine>.<tailnet>.ts.net/`.

Two things need root **once per machine**. The installer detects and prints
them rather than prompting for a password:

```
sudo loginctl enable-linger $USER     # user units start at boot
sudo tailscale set --operator=$USER   # tailscale serve without sudo
```

Then re-run `install.sh`. From here on, nothing needs sudo:

```
systemctl --user restart tmux-web ttyd   # after editing bin/ or the env file
journalctl --user -u tmux-web -f
bash install.sh                          # re-run after git pull (idempotent)
bash uninstall.sh
```

## Configure

`~/.config/tmux-web/env`:

| Variable | Default | Meaning |
|---|---|---|
| `TMUX_WEB_PORT` | `7680` | landing page port (localhost) |
| `TTYD_PORT` | `7681` | ttyd port (localhost) |
| `TMUX_WEB_TITLE` | hostname | page title, tab title, PWA name |
| `TMUX_WEB_DIRS` | `~/projects:~/src:~/workspace:~` | directories offered for new sessions |
| `TMUX_WEB_TOOLS` | `claude=Claude Code,codex=Codex` | coding tools offered besides a shell, `command=Label` |
| `TMUX_WEB_TERM` | `/term/` | URL path your proxy mounts ttyd on |
| `TTYD_EXTRA_ARGS` | | e.g. `-b /term` if your proxy does not strip the prefix |

A coding-tool session runs the tool in front of a login shell, so if it isn't
installed or isn't logged in you land on its error message and a prompt
instead of a session that vanished. Shells with a start command, and
shortcuts, work the same way: the command runs, then you get a prompt.

Shortcuts are stored in `~/.config/tmux-web/shortcuts.json`.

## How it fits together

```
browser ──HTTPS──▶ tailscale serve ──┬── /       ──▶ 127.0.0.1:7680  bin/tmux-web   (page, JSON API)
                                     └── /term/  ──▶ 127.0.0.1:7681  ttyd ──▶ bin/tmux-attach.sh <session>
                                                                                    └─▶ tmux attach
```

Both services run as you and talk to your normal tmux server, so the sessions
shown are the same ones `tmux ls` shows in any other login. Opening a session
loads `/s/<name>`, whose bar sits over an iframe of `/term/?arg=<name>`; ttyd
passes the argument to `tmux-attach.sh`, which attaches. If ttyd is opened
without an argument it falls back to an fzf picker.

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

## License

MIT.
