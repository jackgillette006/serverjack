# FAQ

Questions this project gets asked first. See the [README](../README.md) for
the full picture, and the
[security model](../README.md#security-model-read-this-first) for the part
that matters most.

## Why not plain ttyd?

serverjack is ttyd plus the parts ttyd doesn't have: a session list, a
launcher for shells and coding agents, and a phone soft-key row for keys a touch
keyboard doesn't send (Esc, Tab, Ctrl, arrows). It runs ttyd behind its own reverse proxy on a private Unix
socket rather than publishing it directly, so every request passes
serverjack's checks — the peer-uid check, the identity check, the `Host:`
check — before a single byte reaches the terminal. If you already have a
ttyd setup you like, keep it; serverjack is for when you also want the
launcher and the session list.

## Why not Claude's own remote control, or Codex's?

Use them. Claude Code's Remote Control and Codex's remote pairing cover
starting and driving *their* agent from *their* app — Claude's server mode
can open several new sessions in a directory you pick, not just follow one
already running — and serverjack doesn't try to compete: no agent status,
no notifications, no chat UI. serverjack is a small private front door for
everything around that: a shell, the `sudo` prompt an agent can't answer for
itself, an existing tmux session, a coding CLI that has no remote-control
feature of its own, and the vendor tools' own install/login/server steps —
doing those from a phone screen is the painful part. In practice most of
what you open with it is a shell or a paste-and-run command.

## Why Tailscale and not a password?

A password serverjack made up would be one more secret to store, rotate, and
leak. Tailscale already knows which of your devices are yours, so publishing
through `tailscale serve` means only devices on your Tailscale network,
subject to your own access rules, can even open a connection — everyone else
gets no listener to talk to, not a login page to guess at. The tradeoff is
real and it's stated plainly, not hidden: serverjack has no password of its
own, so anyone who can reach it gets a shell as the account running it, and
identity comes entirely from Tailscale, or from your own reverse proxy, never
from serverjack itself.

## Does it phone home?

No. serverjack sends no telemetry, no analytics, no crash reports, and no
update checks — there is no code path in it that makes an outbound request
on its own. The only two outbound requests anywhere in this project happen
once, during install: `install.sh` downloads the ttyd and fzf binaries from
GitHub over HTTPS and checks them against sha256 hashes pinned in the
install script itself, not fetched from the same host as the binaries. After
that, the only network traffic is what you generate: your browser talking to
serverjack over your Tailscale network, and whatever the coding agents you
start do on their own.

## Does it work without Tailscale?

Yes. Tailscale is optional but recommended, because it handles
authentication for you with no extra setup. Without it, put serverjack
behind a reverse proxy that authenticates on its own — a VPN-only interface,
mTLS, or an SSO proxy like oauth2-proxy or Authelia — and never expose the
plain port to the internet. `examples/nginx.conf` is a working starting
point: one backend, the WebSocket upgrade passed through, and the identity
header stripped from the client and set only by a proxy that has actually
verified the user.
