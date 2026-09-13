#!/usr/bin/env bash
# serverjack installer. Idempotent -- re-run after pulling changes. It never
# prompts for a password: any root step is printed for you to paste.
#
#   bash install.sh              install/refresh and (re)start
#   bash install.sh --no-serve   skip the tailscale serve step
#   bash install.sh --tcp        listen on a 127.0.0.1 port (the default; other
#                                local users are refused by a peer-uid check)
#   bash install.sh --unix       listen on a private Unix socket instead --
#                                needs `tailscale serve` run as root ONCE
#   bash install.sh --port N --https-port N --title NAME
#                                port and page name; a second Linux account on
#                                this machine needs its own port, --https-port
#                                and --title
#
# What it does, all inside your own account:
#   1. puts ttyd and fzf static binaries in ~/.local/bin (verified against
#      checksums pinned in this script)
#   2. writes ~/.config/serverjack/env with defaults if it doesn't exist
#   3. installs two *user* systemd units and starts them
#   4. publishes serverjack with `tailscale serve` -- ONE mount, "/" (tailnet
#      only, never funnel). ttyd is not published: it listens on a private
#      Unix socket and serverjack proxies /term/ to it.
#
# Two things need root exactly ONCE per machine, and this script tells you
# when they're missing instead of asking for your password:
#   - `loginctl enable-linger $USER`   so the user units start at boot
#   - `tailscale set --operator=$USER` so serve doesn't need sudo
# (--unix adds a third: tailscale will not proxy to a Unix socket for anyone
# but root, even the operator, so those two serve lines have to be pasted with
# sudo. That is exactly why tcp is the default.)
#
# After that the daily loop is:  systemctl --user restart serverjack serverjack-ttyd

set -euo pipefail
# Non-login shells (ssh host 'bash install.sh', containers) may not export USER.
USER=${USER:-$(id -un)}
cd "$(dirname "$(readlink -f "$0")")"
REPO=$PWD
BIN=$HOME/.local/bin
CFG_DIR=$HOME/.config/serverjack
ENV_FILE=$CFG_DIR/env
UNIT_DIR=$HOME/.config/systemd/user
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
NO_SERVE=0
OPT_LISTEN=
# Empty unless passed on the command line. A flag sets the value in a NEW env
# file, and rewrites that one line in an existing one -- everything else kept.
OPT_PORT=; OPT_HTTPS_PORT=; OPT_TITLE=
usage() { sed -n '2,17p' "$0"; exit "${1:-0}"; }
while (( $# )); do
  case "$1" in
    --no-serve)   NO_SERVE=1 ;;
    --unix)       OPT_LISTEN=unix ;;
    --tcp)        OPT_LISTEN=tcp ;;
    --port)       OPT_PORT=${2:?--port needs a number}; shift ;;
    # ttyd has no port any more -- it is behind serverjack on a Unix socket.
    --ttyd-port)  echo "--ttyd-port: no longer needed, ttyd is behind serverjack now (ignored)" >&2; shift ;;
    --ttyd-port=*) echo "--ttyd-port: no longer needed, ttyd is behind serverjack now (ignored)" >&2 ;;
    --https-port) OPT_HTTPS_PORT=${2:?--https-port needs a number}; shift ;;
    --title)      OPT_TITLE=${2:?--title needs a name}; shift ;;
    --port=*)       OPT_PORT=${1#*=} ;;
    --https-port=*) OPT_HTTPS_PORT=${1#*=} ;;
    --title=*)      OPT_TITLE=${1#*=} ;;
    -h|--help)    usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 >&2 ;;
  esac
  shift
done
# Asking for a port only makes sense if we are listening on ports.
if [[ -n $OPT_PORT ]]; then
  [[ $OPT_LISTEN == unix ]] && { echo "--unix and --port contradict each other" >&2; exit 1; }
  OPT_LISTEN=tcp
fi
for p in "$OPT_PORT" "$OPT_HTTPS_PORT"; do
  [[ -z $p ]] && continue
  [[ $p =~ ^[0-9]{1,5}$ ]] || { echo "not a port number: $p" >&2; exit 1; }
  (( 10#$p >= 1 && 10#$p <= 65535 )) \
    || { echo "port must be between 1 and 65535: $p" >&2; exit 1; }
done
# tailscale only terminates HTTPS on these three ports.
[[ -z $OPT_HTTPS_PORT || $OPT_HTTPS_PORT =~ ^(443|8443|10000)$ ]] \
  || { echo "--https-port must be 443, 8443 or 10000 (tailscale serve only listens on those)" >&2; exit 1; }
[[ $OPT_TITLE != *$'\n'* && $OPT_TITLE != *$'\r'* ]] \
  || { echo "--title cannot contain a newline" >&2; exit 1; }

TTYD_VER=1.7.7
FZF_VER=0.74.3
# sha256 of every asset we might download, copied from the projects' own
# published SHA256SUMS / checksums files. Pinned HERE on purpose: fetching the
# checksum file from the same host as the binary proves only that the two
# agree, so whoever can swap one can swap the other. A mismatch means the
# release was re-cut or something is wrong -- check before bumping these.
declare -A SHA256=(
  [ttyd.x86_64]=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
  [ttyd.aarch64]=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
  [ttyd.armhf]=8240c8438b68d3b10b0e1a4e7c914d70fca6a7606b516f40bf40adfa1044d801
  [fzf-0.74.3-linux_amd64.tar.gz]=3501a595e4b5c40a6b047340a0e8f805c46fd4e61ef95ef8a136ba8c61cf6f22
  [fzf-0.74.3-linux_arm64.tar.gz]=4a17a17b46bd0c4873e995533de508995c11572c0be0664a5dbcf13f60463046
  [fzf-0.74.3-linux_armv7.tar.gz]=d290204a7e901cf18067d338f53876aa0ab5d666eb626addb4dcc97f9fd2dfa5
)
# Every download in this script: HTTPS only, and no redirect may leave it.
fetch() { curl -fsSL --proto '=https' --proto-redir '=https' "$@"; }
# Verify a downloaded file against the pinned hash, then (belt and braces)
# against the project's own checksum file for the same asset.
verify() {  # $1 file in $tmp, $2 asset name, $3 URL of the project's sums file
  local want=${SHA256[$2]:-}
  [[ -n $want ]] || { echo "no pinned sha256 for $2 -- refusing to install it" >&2; exit 1; }
  echo "$want  $1" | (cd "$tmp" && sha256sum -c - >/dev/null) || {
    echo "$2 does not match the sha256 pinned in install.sh -- refusing to install it" >&2; exit 1; }
  if fetch -o "$tmp/sums.$$" "$3" 2>/dev/null; then
    grep -q "^$want  $2\$" "$tmp/sums.$$" \
      || echo "  note: $2 matches the pinned hash but not $3 (upstream re-cut a release?)" >&2
    rm -f "$tmp/sums.$$"
  fi
}
todo=()

say() { printf '\033[1m%s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }; }
need tmux; need curl; need python3; need systemctl

# ---------------------------------------------------------------- binaries
[[ ! -L $CFG_DIR ]] || { echo "$CFG_DIR is a symlink -- refusing to store private configuration there" >&2; exit 1; }
mkdir -p "$BIN" "$CFG_DIR" "$UNIT_DIR"
chmod 700 "$CFG_DIR"
[[ ! -L $ENV_FILE ]] || { echo "$ENV_FILE is a symlink -- refusing" >&2; exit 1; }
arch=$(uname -m)
case "$arch" in
  x86_64)  ttyd_asset=ttyd.x86_64;  fzf_asset=fzf-$FZF_VER-linux_amd64.tar.gz ;;
  aarch64) ttyd_asset=ttyd.aarch64; fzf_asset=fzf-$FZF_VER-linux_arm64.tar.gz ;;
  armv7l)  ttyd_asset=ttyd.armhf;   fzf_asset=fzf-$FZF_VER-linux_armv7.tar.gz ;;
  *) echo "unsupported arch $arch -- install ttyd and fzf yourself into $BIN" >&2; exit 1 ;;
esac
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

if ! "$BIN/ttyd" --version 2>/dev/null | grep -q "$TTYD_VER"; then
  say "Installing ttyd $TTYD_VER -> $BIN/ttyd"
  base=https://github.com/tsl0922/ttyd/releases/download/$TTYD_VER
  fetch -o "$tmp/$ttyd_asset" "$base/$ttyd_asset"
  verify "$ttyd_asset" "$ttyd_asset" "$base/SHA256SUMS"
  install -m 755 "$tmp/$ttyd_asset" "$BIN/ttyd"
fi
if ! "$BIN/fzf" --version 2>/dev/null | grep -q "^$FZF_VER"; then
  say "Installing fzf $FZF_VER -> $BIN/fzf"
  base=https://github.com/junegunn/fzf/releases/download/v$FZF_VER
  fetch -o "$tmp/$fzf_asset" "$base/$fzf_asset"
  verify "$fzf_asset" "$fzf_asset" "$base/fzf_${FZF_VER}_checksums.txt"
  tar -xzf "$tmp/$fzf_asset" -C "$tmp" fzf
  install -m 755 "$tmp/fzf" "$BIN/fzf"
fi

# ---------------------------------------------------------------- config
if [[ ! -f "$ENV_FILE" ]]; then
  say "Writing $ENV_FILE (edit it, then: systemctl --user restart serverjack serverjack-ttyd)"
  cat > "$ENV_FILE" <<CFG
# serverjack configuration. Restart after editing:
#   systemctl --user restart serverjack serverjack-ttyd
PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
# How serverjack listens. (ttyd is always on a private Unix socket behind it;
# there is only ever one listener to publish.) "tcp" (default): the 127.0.0.1
# port below. Other local accounts can open that, so serverjack looks every
# connection's owner up in /proc/net/tcp and only answers root (tailscaled) and
# you -- SERVERJACK_TRUST_UIDS adds a proxy's uid, SERVERJACK_TRUST_LOCAL=1
# turns the check off. "unix": a socket in \$XDG_RUNTIME_DIR/serverjack, 0600 in
# a 0700 directory, which the kernel enforces -- but \`tailscale serve\` then has
# to be pointed at it once as root.
SERVERJACK_LISTEN=${OPT_LISTEN:-tcp}
#SERVERJACK_TRUST_UIDS=101
# Whose Tailscale-User-Login header to believe. root (tailscaled) always is;
# add a proxy's uid ONLY if that proxy authenticates the user itself and strips
# the client's copy of the header.
#SERVERJACK_TRUST_IDENTITY_UIDS=
# Port, used only when SERVERJACK_LISTEN=tcp.
SERVERJACK_PORT=${OPT_PORT:-7680}
# HTTPS port \`tailscale serve\` publishes on (443, 8443 or 10000). serve is
# machine-wide, so a second account on this box needs its own port here.
SERVERJACK_HTTPS_PORT=${OPT_HTTPS_PORT:-443}
SERVERJACK_TITLE=${OPT_TITLE:-$(hostname -s)}
# Directories offered when starting a session (colon-separated, ~ ok)
SERVERJACK_DIRS=~/projects:~/src:~/workspace:~
# Coding tools come from a registry: the built-ins (Claude Code, Codex, OpenCode,
# Copilot CLI, Gemini CLI) plus $CFG_DIR/tools.json, whose entries are merged
# over the built-ins by "id" -- that is where you add or override a tool.
# SERVERJACK_TOOLS is optional: a comma-separated list of ids that restricts and
# orders which cards are shown. Leave it unset to show them all.
#SERVERJACK_TOOLS=claude,codex
# URL path serverjack serves the terminal on (it proxies it to ttyd's socket)
SERVERJACK_TERM=/term/
# Extra Host: values to answer to, comma-separated. 127.0.0.1, localhost,
# [::1], this machine's hostname and its tailnet name are always accepted;
# anything else gets a 421. Add your own name here if you front this with a
# reverse proxy on some other domain.
#SERVERJACK_HOSTS=term.example.com
# Extra ttyd flags (rarely needed -- serverjack strips the /term prefix itself)
TTYD_EXTRA_ARGS=
# user@host used by "Copy SSH command" / "Open in SSH app" (auto: tailnet name); "off" hides them
#SERVERJACK_SSH=
# Sessions opened from the page get tmux's status line hidden (the page bar
# shows tabs and window count). Set to on to leave tmux's status line alone.
#SERVERJACK_TMUX_STATUS=off
# Restrict this instance to named tailnet logins (comma-separated), e.g.
# alice@github. Anyone else who reaches it gets a 403 page -- the terminal
# included, since serverjack serves that too. Unset means the tailnet itself is
# the trust boundary.
#SERVERJACK_ALLOW=
CFG
  chmod 600 "$ENV_FILE"
fi
[[ -f $ENV_FILE && ! -L $ENV_FILE ]] \
  || { echo "$ENV_FILE is not a regular file, or is a symlink -- refusing" >&2; exit 1; }
chmod 700 "$CFG_DIR"
chmod 600 "$ENV_FILE"
# Read the few values we need the way systemd does (KEY=value, optional
# quotes) -- NOT with `source`, which chokes on unquoted spaces like "Claude Code".
cfg() {
  local key=$1 fallback=${2-} line v=
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line == "$key="* ]] && v=${line#*=}
  done < "$ENV_FILE"
  v=${v#\"}; v=${v%\"}
  printf '%s' "${v:-$fallback}"
}
cfg_has() {
  local key=$1 line
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line == "$key="* ]] && return 0
  done < "$ENV_FILE"
  return 1
}
# Explicitly-passed flags update an existing env file: rewrite that one line in
# place (or append it if the file predates the setting), keep everything else.
setcfg() {
  local key=$1 val=$2 encoded line found=0 cfg_tmp
  [[ $val != *$'\n'* && $val != *$'\r'* ]] \
    || { echo "$key cannot contain a newline" >&2; exit 1; }
  encoded=${val//\\/\\\\}
  encoded=${encoded//\"/\\\"}
  encoded=\"$encoded\"
  if cfg_has "$key"; then
    [[ "$(cfg "$key")" == "$val" ]] && return 0
    cfg_tmp=$(mktemp "$CFG_DIR/.env.XXXXXX")
    while IFS= read -r line || [[ -n $line ]]; do
      if [[ $line == "$key="* ]]; then
        if (( ! found )); then
          printf '%s=%s\n' "$key" "$encoded" >> "$cfg_tmp"
          found=1
        fi
      else
        printf '%s\n' "$line" >> "$cfg_tmp"
      fi
    done < "$ENV_FILE"
    chmod 600 "$cfg_tmp"
    mv -f -- "$cfg_tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$encoded" >> "$ENV_FILE"
  fi
  say "Set $key=$val in $ENV_FILE"
}
SERVERJACK_PORT=${OPT_PORT:-$(cfg SERVERJACK_PORT 7680)}
HTTPS_PORT=${OPT_HTTPS_PORT:-$(cfg SERVERJACK_HTTPS_PORT 443)}
SERVERJACK_TERM=$(cfg SERVERJACK_TERM /term/)
LEGACY_TTYD_PORT=$(cfg TTYD_PORT '')
# An env file written before this setting existed has no line for it and gets
# the default, tcp -- which is what it was already doing, so an install that is
# only being refreshed keeps working and its serve mounts stay correct.
LISTEN=${OPT_LISTEN:-$(cfg SERVERJACK_LISTEN tcp)}
[[ $LISTEN == tcp || $LISTEN == unix ]] \
  || { echo "SERVERJACK_LISTEN must be tcp or unix, got: $LISTEN" >&2; exit 1; }
[[ $SERVERJACK_PORT =~ ^[0-9]{1,5}$ ]] \
  || { echo "SERVERJACK_PORT must be an integer from 1 to 65535" >&2; exit 1; }
SERVERJACK_PORT=$((10#$SERVERJACK_PORT))
(( SERVERJACK_PORT >= 1 && SERVERJACK_PORT <= 65535 )) \
  || { echo "SERVERJACK_PORT must be an integer from 1 to 65535" >&2; exit 1; }
[[ $HTTPS_PORT =~ ^(443|8443|10000)$ ]] \
  || { echo "SERVERJACK_HTTPS_PORT must be 443, 8443 or 10000" >&2; exit 1; }
[[ $SERVERJACK_TERM =~ ^/[A-Za-z0-9._~/-]+/?$ && $SERVERJACK_TERM != / ]] \
  || { echo "SERVERJACK_TERM must be a simple absolute subpath such as /term/" >&2; exit 1; }
SERVERJACK_TERM=/${SERVERJACK_TERM#/}
SERVERJACK_TERM=${SERVERJACK_TERM%/}/
if [[ -n $LEGACY_TTYD_PORT ]]; then
  if [[ $LEGACY_TTYD_PORT =~ ^[0-9]{1,5}$ ]] \
      && (( 10#$LEGACY_TTYD_PORT >= 1 && 10#$LEGACY_TTYD_PORT <= 65535 )); then
    LEGACY_TTYD_PORT=$((10#$LEGACY_TTYD_PORT))
  else
    # A corrupt legacy value must never be used to claim a machine-wide route.
    LEGACY_TTYD_PORT=
  fi
fi
# Validate the complete effective configuration before changing the existing
# file. Thus a bad saved TERM, for example, cannot result in a successful port
# rewrite followed by a validation failure.
[[ -n $OPT_LISTEN     ]] && setcfg SERVERJACK_LISTEN     "$OPT_LISTEN"
[[ -n $OPT_PORT       ]] && setcfg SERVERJACK_PORT       "$OPT_PORT"
[[ -n $OPT_HTTPS_PORT ]] && setcfg SERVERJACK_HTTPS_PORT "$OPT_HTTPS_PORT"
[[ -n $OPT_TITLE      ]] && setcfg SERVERJACK_TITLE      "$OPT_TITLE"
RUNTIME=${XDG_RUNTIME_DIR}/serverjack
mkdir -p "$RUNTIME"; chmod 700 "$RUNTIME"
if [[ $LISTEN == tcp ]]; then
  WEB_BACKEND=http://127.0.0.1:$SERVERJACK_PORT
else
  WEB_BACKEND=unix:$RUNTIME/web.sock
fi

# ---------------------------------------------------------------- port clashes
port_free() { ! ss -ltnp 2>/dev/null | grep -q ":$1 "; }
# ss shows the listener as users:(("python3",pid=...)) -- we can't see WHOSE it
# is without root, but the process name is enough to guess "another account's".
port_holder() { ss -ltnp 2>/dev/null | grep ":$1 " | grep -o 'users:.*' | head -1; }
# First free (n, n+1) pair at or after $1, so the remedy suggests real ports.
free_pair() {
  local p=$1
  while (( p < 65000 )); do
    port_free "$p" && port_free "$((p+1))" && { printf '%s' "$p"; return; }
    p=$((p+10))
  done
  printf '%s' "$1"
}
# An HTTPS port for this account that nothing else is serving on.
free_https() {
  local p
  for p in 443 8443 10000; do
    [[ -z "$(serve_backend_for "$p" /)" ]] && { printf '%s' "$p"; return; }
  done
  printf '8443'
}
# Backend `tailscale serve` currently proxies <https port><path> to, as it
# prints it: "http://127.0.0.1:7680" or "unix:/run/user/1000/serverjack/web.sock".
serve_backend_for() {
  command -v tailscale >/dev/null 2>&1 || return 0
  tailscale serve status 2>/dev/null | awk -v wp="$1" -v wpath="$2" '
    /^https:\/\// { h=$1; sub(/^https:\/\//,"",h); n=split(h,a,":");
                    cur=(n>1 ? a[n] : "443"); next }
    /^\|--/ && cur==wp && $2==wpath { print $NF; exit }'
}
backend_is_ours() {
  local backend=$1
  [[ $backend == "http://127.0.0.1:$SERVERJACK_PORT" \
     || $backend == "unix:$RUNTIME/web.sock" \
     || $backend == "unix:$RUNTIME/ttyd.sock" \
     || ( -n $LEGACY_TTYD_PORT && $backend == "http://127.0.0.1:$LEGACY_TTYD_PORT" ) ]]
}
remedy() {  # $1 = why, printed first
  local p; p=$(free_pair $(( SERVERJACK_PORT + 10 )))
  echo "$1" >&2
  echo "Pick a free port and a free HTTPS port for this account, e.g.:" >&2
  echo "  bash $REPO/install.sh --port $p --https-port $(free_https)" >&2
  echo "  (add --title $USER-serverjack so the two pages are told apart on a phone)" >&2
}

# refuse to fight another process for the ports (e.g. an older system-level
# install, or another Linux account's serverjack). Only a tcp-mode concern:
# Unix sockets live in a per-account runtime dir and cannot collide, and a
# second copy of *your own* instance is handled by the unit restart.
for port in $([[ $LISTEN == tcp ]] && echo "$SERVERJACK_PORT"); do
  if ! port_free "$port" && ! systemctl --user is-active --quiet serverjack serverjack-ttyd 2>/dev/null; then
    holder=$(port_holder "$port")
    if [[ $holder == *'"python3"'* || $holder == *'"ttyd"'* || $holder == *'"serverjack"'* ]]; then
      whose="another process (probably another user's serverjack)"
    else
      whose="another process"
    fi
    remedy "port $port is in use by $whose: $holder"
    exit 1
  fi
done

# ---------------------------------------------------------------- units
for u in serverjack serverjack-ttyd; do
  python3 - "$REPO" "systemd/$u.service" "$tmp/$u.service" <<'PY'
import pathlib
import sys

repo, source, target = sys.argv[1:]
if any(char in repo for char in "\n\r\0"):
    raise SystemExit("repository path contains a control character -- refusing")
# Quoted systemd command arguments still expand percent specifiers. Backslash
# and quote are the only other characters needing protection inside quotes.
escaped = repo.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
pathlib.Path(target).write_text(pathlib.Path(source).read_text().replace("@REPO@", escaped))
PY
  install -m 644 "$tmp/$u.service" "$UNIT_DIR/$u.service"
done
systemctl --user daemon-reload

say "Starting user units"
systemctl --user enable serverjack serverjack-ttyd >/dev/null 2>&1
systemctl --user restart serverjack serverjack-ttyd
sleep 1
systemctl --user --no-pager is-active serverjack serverjack-ttyd | paste -sd' ' | sed 's/^/  serverjack serverjack-ttyd: /'
if [[ $LISTEN == tcp ]]; then
  curl -s -o /dev/null -w "  landing  http://127.0.0.1:$SERVERJACK_PORT/  -> HTTP %{http_code}\n" "http://127.0.0.1:$SERVERJACK_PORT/healthz"
  curl -s -o /dev/null -w "  terminal http://127.0.0.1:$SERVERJACK_PORT$SERVERJACK_TERM  -> HTTP %{http_code}\n" "http://127.0.0.1:$SERVERJACK_PORT$SERVERJACK_TERM"
else
  curl -s -o /dev/null --unix-socket "$RUNTIME/web.sock" \
    -w "  landing  $RUNTIME/web.sock  -> HTTP %{http_code}\n" http://serverjack/healthz
  curl -s -o /dev/null --unix-socket "$RUNTIME/web.sock" \
    -w "  terminal $RUNTIME/web.sock$SERVERJACK_TERM -> HTTP %{http_code}\n" "http://serverjack$SERVERJACK_TERM"
fi

# ---------------------------------------------------------------- boot persistence
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
  todo+=("sudo loginctl enable-linger $USER      # so the user units start at boot, not at first login")
fi

# ---------------------------------------------------------------- tailscale serve
if (( ! NO_SERVE )) && command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
  say "Publishing on the tailnet (tailscale serve, HTTPS $HTTPS_PORT, tailnet only)"
  mount=${SERVERJACK_TERM%/}
  # ONE mount now: "/" -> serverjack, which serves the terminal itself. An
  # install from before that change also published <mount> -> ttyd's port; that
  # mount is now a way straight past serverjack's checks, so take it down.
  stale=$(serve_backend_for "$HTTPS_PORT" "$mount")
  if [[ -n $stale ]]; then
    if backend_is_ours "$stale"; then
      if tailscale serve --https="$HTTPS_PORT" --set-path="$mount" off >/dev/null 2>&1; then
        say "Removed the old $mount serve mount ($stale) -- the terminal now goes through serverjack"
      else
        stale_clash="could not remove this account's old $mount mount ($stale)"
      fi
    else
      stale_clash="$mount already proxies to $stale, which is not this account's configured backend"
    fi
  fi
  # `tailscale serve` is machine-wide, not per-user: whoever runs it owns that
  # (https port, path). Don't take over a mount that points somewhere else --
  # that would be silently unpublishing another account's serverjack.
  clash=${stale_clash:-}
  cur=$(serve_backend_for "$HTTPS_PORT" /)
  # Ours either way: the same backend, or the tcp/unix backend of this same
  # account that we are about to replace (serve config is keyed by port+path,
  # so re-running with the new backend just replaces that mount).
  if [[ -z $clash && -n $cur ]] && ! backend_is_ours "$cur"; then
    clash="https://<host>:$HTTPS_PORT/ already proxies to $cur, not our $WEB_BACKEND"
  fi
  if [[ -n $clash ]]; then
    remedy "tailscale serve conflict: $clash (probably another user's serverjack)."
    echo "Skipped tailscale serve; the local units are running ($WEB_BACKEND)." >&2
  elif out=$(tailscale serve --bg --https="$HTTPS_PORT" "$WEB_BACKEND" 2>&1); then
    tailscale serve status | sed 's/^/  /'
    host=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
    hostport=$host; [[ $HTTPS_PORT != 443 ]] && hostport=$host:$HTTPS_PORT
    [[ -n "$host" ]] && say "Open: https://$hostport/"
  else
    both="${out:-}"
    if [[ $LISTEN != tcp ]] && grep -qi "must be root" <<<"$both"; then
      echo "WARNING: serverjack now listens on a Unix socket, but tailscale serve" >&2
      echo "still proxies https://<host>:$HTTPS_PORT to the old port, so the URL will" >&2
      echo "502 until you paste the two lines below (or re-run with --tcp)." >&2
      # Verified on tailscale 1.102.3: proxying to a Unix socket needs root
      # even for the operator --
      #   401 Unauthorized: must be root, or be an operator and able to run
      #   'sudo tailscale' to serve a path or Unix socket
      # The serve config is persistent, so this is a one-time step like the two
      # above, not something the daily loop needs.
      todo+=("sudo tailscale serve --bg --https=$HTTPS_PORT $WEB_BACKEND
   # \`tailscale serve\` needs root to proxy to a Unix socket (the operator grant
   # is not enough; it said: $(grep -o "must be root[^\"]*" <<<"$both" | head -1)).
   # Serve config persists across reboots, so this is once per machine.
   # Prefer no root at all? Re-run: bash $REPO/install.sh --tcp
   # -- that goes back to 127.0.0.1 ports, which ANY local account can connect to.")
    elif grep -qi "denied" <<<"$both"; then
      todo+=("sudo tailscale set --operator=$USER   # then re-run install.sh: serve without sudo.
   NOTE: --operator takes ONE username for the whole machine. If another account
   already has it, either leave serve to that account (install.sh --no-serve) or
   run the serve commands with sudo from this one.")
    else
      echo "tailscale serve failed:"; echo "${out:-}"
    fi
  fi
else
  (( NO_SERVE )) || echo "tailscale not found/up: expose it yourself behind something that authenticates (see examples/nginx.conf)"
fi

# ---------------------------------------------------------------- summary
echo
if (( ${#todo[@]} )); then
  say "One-time root steps still needed (then re-run: bash install.sh):"
  printf '  %s\n' "${todo[@]}"
  echo
fi
say "Daily commands (no sudo):"
cat <<TXT
  systemctl --user restart serverjack serverjack-ttyd   # after editing bin/ or $ENV_FILE
  journalctl --user -u serverjack -f                    # page + API logs
  journalctl --user -u serverjack-ttyd -f               # terminal logs
  systemctl --user status serverjack serverjack-ttyd
  bash $REPO/install.sh                                 # re-run after a git pull (idempotent)
  bash $REPO/uninstall.sh
TXT
