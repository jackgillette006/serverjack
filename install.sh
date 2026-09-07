#!/usr/bin/env bash
# serverjack installer. NO sudo. Idempotent -- re-run after pulling changes.
#
#   bash install.sh              install/refresh and (re)start
#   bash install.sh --no-serve   skip the tailscale serve step
#   bash install.sh --port N --ttyd-port N --https-port N --title NAME
#                                pick ports/name -- needed when a second Linux
#                                account on this machine also runs serverjack
#
# What it does, all inside your own account:
#   0. migrates an older tmux-web install (env file, shortcuts, old user units)
#   1. puts ttyd and fzf static binaries in ~/.local/bin (checksum-verified)
#   2. writes ~/.config/serverjack/env with defaults if it doesn't exist
#   3. installs two *user* systemd units and starts them
#   4. publishes them with `tailscale serve` (tailnet only, never funnel)
#
# Two things need root exactly ONCE per machine, and this script tells you
# when they're missing instead of asking for your password:
#   - `loginctl enable-linger $USER`   so the user units start at boot
#   - `tailscale set --operator=$USER` so serve doesn't need sudo
#
# After that the daily loop is:  systemctl --user restart serverjack serverjack-ttyd

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$PWD
BIN=$HOME/.local/bin
CFG_DIR=$HOME/.config/serverjack
ENV_FILE=$CFG_DIR/env
UNIT_DIR=$HOME/.config/systemd/user
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
NO_SERVE=0
# Empty unless passed on the command line. A flag sets the value in a NEW env
# file, and rewrites that one line in an existing one -- everything else kept.
OPT_PORT=; OPT_TTYD_PORT=; OPT_HTTPS_PORT=; OPT_TITLE=
usage() { sed -n '2,8p' "$0"; exit "${1:-0}"; }
while (( $# )); do
  case "$1" in
    --no-serve)   NO_SERVE=1 ;;
    --port)       OPT_PORT=${2:?--port needs a number}; shift ;;
    --ttyd-port)  OPT_TTYD_PORT=${2:?--ttyd-port needs a number}; shift ;;
    --https-port) OPT_HTTPS_PORT=${2:?--https-port needs a number}; shift ;;
    --title)      OPT_TITLE=${2:?--title needs a name}; shift ;;
    --port=*)       OPT_PORT=${1#*=} ;;
    --ttyd-port=*)  OPT_TTYD_PORT=${1#*=} ;;
    --https-port=*) OPT_HTTPS_PORT=${1#*=} ;;
    --title=*)      OPT_TITLE=${1#*=} ;;
    -h|--help)    usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 >&2 ;;
  esac
  shift
done
for p in "$OPT_PORT" "$OPT_TTYD_PORT" "$OPT_HTTPS_PORT"; do
  [[ -z $p || $p =~ ^[0-9]+$ ]] || { echo "not a port number: $p" >&2; exit 1; }
done
# tailscale only terminates HTTPS on these three ports.
[[ -z $OPT_HTTPS_PORT || $OPT_HTTPS_PORT =~ ^(443|8443|10000)$ ]] \
  || { echo "--https-port must be 443, 8443 or 10000 (tailscale serve only listens on those)" >&2; exit 1; }

TTYD_VER=1.7.7
FZF_VER=0.74.3
todo=()

say() { printf '\033[1m%s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }; }
need tmux; need curl; need python3; need systemctl

# ---------------------------------------------------------------- binaries
mkdir -p "$BIN" "$CFG_DIR" "$UNIT_DIR"
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
  curl -fsSL -o "$tmp/$ttyd_asset" "$base/$ttyd_asset"
  curl -fsSL -o "$tmp/SHA256SUMS" "$base/SHA256SUMS"
  (cd "$tmp" && grep " $ttyd_asset\$" SHA256SUMS | sha256sum -c - >/dev/null)
  install -m 755 "$tmp/$ttyd_asset" "$BIN/ttyd"
fi
if ! "$BIN/fzf" --version 2>/dev/null | grep -q "^$FZF_VER"; then
  say "Installing fzf $FZF_VER -> $BIN/fzf"
  base=https://github.com/junegunn/fzf/releases/download/v$FZF_VER
  curl -fsSL -o "$tmp/$fzf_asset" "$base/$fzf_asset"
  curl -fsSL -o "$tmp/sums" "$base/fzf_${FZF_VER}_checksums.txt"
  (cd "$tmp" && grep " $fzf_asset\$" sums | sha256sum -c - >/dev/null)
  tar -xzf "$tmp/$fzf_asset" -C "$tmp" fzf
  install -m 755 "$tmp/fzf" "$BIN/fzf"
fi

# ---------------------------------------------------------------- migrate from tmux-web
# The project used to be called tmux-web. Move an existing install over once:
# convert the env file, drop the old user units (which hold ports 7680/7681).
OLD_CFG_DIR=$HOME/.config/tmux-web
OLD_ENV=$OLD_CFG_DIR/env
migrated=()
if [[ ! -f "$ENV_FILE" && -f "$OLD_ENV" ]]; then
  sed -e '/^[[:space:]]*#.*Coding tools offered besides a plain shell/d' \
      -e '/^[[:space:]]*TMUX_WEB_TOOLS=/c\
# Coding tools now live in a registry: built-ins plus ~/.config/serverjack/tools.json,\
# whose entries are merged over the built-ins by "id" (see the README).\
# SERVERJACK_TOOLS is optional and only restricts/orders which ids are shown:\
#SERVERJACK_TOOLS=claude,codex' \
      -e 's/TMUX_WEB_/SERVERJACK_/g' \
      -e 's/^# tmux-web configuration/# serverjack configuration/' \
      -e 's/systemctl --user restart tmux-web ttyd/systemctl --user restart serverjack serverjack-ttyd/' \
      "$OLD_ENV" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  migrated+=("$OLD_ENV -> $ENV_FILE (TMUX_WEB_* renamed to SERVERJACK_*; old file left in place)")
fi
if [[ -f "$OLD_CFG_DIR/shortcuts.json" && ! -f "$CFG_DIR/shortcuts.json" ]]; then
  cp -p "$OLD_CFG_DIR/shortcuts.json" "$CFG_DIR/shortcuts.json"
  migrated+=("$OLD_CFG_DIR/shortcuts.json -> $CFG_DIR/shortcuts.json")
fi
old_units=()
for u in tmux-web ttyd; do
  [[ -f "$UNIT_DIR/$u.service" ]] && old_units+=("$u")
done
if (( ${#old_units[@]} )); then
  systemctl --user disable --now "${old_units[@]}" >/dev/null 2>&1 || true
  for u in "${old_units[@]}"; do rm -f "$UNIT_DIR/$u.service"; done
  systemctl --user daemon-reload
  migrated+=("stopped and removed old user units: ${old_units[*]} (they are now serverjack, serverjack-ttyd)")
fi
if (( ${#migrated[@]} )); then
  say "Migrated from the old tmux-web install:"
  printf '  %s\n' "${migrated[@]}"
fi

# ---------------------------------------------------------------- config
if [[ ! -f "$ENV_FILE" ]]; then
  say "Writing $ENV_FILE (edit it, then: systemctl --user restart serverjack serverjack-ttyd)"
  cat > "$ENV_FILE" <<CFG
# serverjack configuration. Restart after editing:
#   systemctl --user restart serverjack serverjack-ttyd
PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
SERVERJACK_PORT=${OPT_PORT:-7680}
TTYD_PORT=${OPT_TTYD_PORT:-7681}
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
# URL path your proxy mounts ttyd on (tailscale serve: /term, prefix stripped)
SERVERJACK_TERM=/term/
# Extra ttyd flags, e.g. "-b /term" if your reverse proxy does NOT strip the prefix
TTYD_EXTRA_ARGS=
# user@host used by "Copy SSH command" / "Open in SSH app" (auto: tailnet name); "off" hides them
#SERVERJACK_SSH=
CFG
  chmod 600 "$ENV_FILE"
fi
# Read the few values we need the way systemd does (KEY=value, optional
# quotes) -- NOT with `source`, which chokes on unquoted spaces like "Claude Code".
cfg() { local v; v=$(grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-); v=${v#\"}; v=${v%\"}; printf '%s' "${v:-$2}"; }
# Explicitly-passed flags update an existing env file: rewrite that one line in
# place (or append it if the file predates the setting), keep everything else.
setcfg() {
  local key=$1 val=$2
  if grep -qE "^$key=" "$ENV_FILE"; then
    [[ "$(cfg "$key")" == "$val" ]] && return 0
    sed -i "s|^$key=.*|$key=$val|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
  say "Set $key=$val in $ENV_FILE"
}
[[ -n $OPT_PORT       ]] && setcfg SERVERJACK_PORT       "$OPT_PORT"
[[ -n $OPT_TTYD_PORT  ]] && setcfg TTYD_PORT             "$OPT_TTYD_PORT"
[[ -n $OPT_HTTPS_PORT ]] && setcfg SERVERJACK_HTTPS_PORT "$OPT_HTTPS_PORT"
[[ -n $OPT_TITLE      ]] && setcfg SERVERJACK_TITLE      "$OPT_TITLE"
SERVERJACK_PORT=$(cfg SERVERJACK_PORT 7680)
TTYD_PORT=$(cfg TTYD_PORT 7681)
HTTPS_PORT=$(cfg SERVERJACK_HTTPS_PORT 443)
SERVERJACK_TERM=$(cfg SERVERJACK_TERM /term/)

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
# Backend port `tailscale serve` currently proxies <https port><path> to, if any.
serve_backend_for() {
  command -v tailscale >/dev/null 2>&1 || return 0
  tailscale serve status 2>/dev/null | awk -v wp="$1" -v wpath="$2" '
    /^https:\/\// { h=$1; sub(/^https:\/\//,"",h); n=split(h,a,":");
                    cur=(n>1 ? a[n] : "443"); next }
    /^\|--/ && cur==wp && $2==wpath { n=split($NF,b,":"); print b[n]; exit }'
}
remedy() {  # $1 = why, printed first
  local p; p=$(free_pair $(( SERVERJACK_PORT + 10 )))
  echo "$1" >&2
  echo "Pick free ports and a free HTTPS port for this account, e.g.:" >&2
  echo "  bash $REPO/install.sh --port $p --ttyd-port $((p+1)) --https-port $(free_https)" >&2
  echo "  (add --title $USER-serverjack so the two pages are told apart on a phone)" >&2
}

# refuse to fight another process for the ports (e.g. an older system-level
# install, or another Linux account's serverjack)
for port in "$SERVERJACK_PORT" "$TTYD_PORT"; do
  if ! port_free "$port" && ! systemctl --user is-active --quiet serverjack serverjack-ttyd 2>/dev/null; then
    holder=$(port_holder "$port")
    if [[ $holder == *'"python3"'* || $holder == *'"ttyd"'* || $holder == *'"serverjack"'* ]]; then
      whose="another process (probably another user's serverjack)"
    else
      whose="another process"
    fi
    remedy "port $port is in use by $whose: $holder"
    if [[ -f /etc/systemd/system/tmux-web.service || -f /etc/systemd/system/ttyd.service ]]; then
      echo "Or, if that is the old system-level tmux-web install, remove it once (needs root):" >&2
      echo "  sudo systemctl disable --now tmux-web ttyd; sudo rm -f /etc/systemd/system/{tmux-web,ttyd}.service; sudo systemctl daemon-reload" >&2
      echo "then re-run: bash $REPO/install.sh" >&2
    fi
    exit 1
  fi
done

# ---------------------------------------------------------------- units
for u in serverjack serverjack-ttyd; do
  sed "s|@REPO@|$REPO|g" "systemd/$u.service" > "$UNIT_DIR/$u.service"
done
systemctl --user daemon-reload

say "Starting user units"
systemctl --user enable serverjack serverjack-ttyd >/dev/null 2>&1
systemctl --user restart serverjack serverjack-ttyd
sleep 1
systemctl --user --no-pager is-active serverjack serverjack-ttyd | paste -sd' ' | sed 's/^/  serverjack serverjack-ttyd: /'
curl -s -o /dev/null -w "  landing  http://127.0.0.1:$SERVERJACK_PORT/  -> HTTP %{http_code}\n" "http://127.0.0.1:$SERVERJACK_PORT/healthz"
curl -s -o /dev/null -w "  ttyd     http://127.0.0.1:$TTYD_PORT/   -> HTTP %{http_code}\n" "http://127.0.0.1:$TTYD_PORT/"

# ---------------------------------------------------------------- boot persistence
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
  todo+=("sudo loginctl enable-linger $USER      # so the user units start at boot, not at first login")
fi

# ---------------------------------------------------------------- tailscale serve
if (( ! NO_SERVE )) && command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
  say "Publishing on the tailnet (tailscale serve, HTTPS $HTTPS_PORT, tailnet only)"
  mount=${SERVERJACK_TERM%/}
  # `tailscale serve` is machine-wide, not per-user: whoever runs it owns that
  # (https port, path). Don't take over a mount that points somewhere else --
  # that would be silently unpublishing another account's serverjack.
  clash=
  for pair in "/ $SERVERJACK_PORT" "$mount $TTYD_PORT"; do
    set -- $pair
    cur=$(serve_backend_for "$HTTPS_PORT" "$1")
    [[ -n $cur && $cur != "$2" ]] && clash="https://<host>:$HTTPS_PORT$1 already proxies to 127.0.0.1:$cur, not our $2"
  done
  if [[ -n $clash ]]; then
    remedy "tailscale serve conflict: $clash (probably another user's serverjack)."
    echo "Skipped tailscale serve; the local units are running on $SERVERJACK_PORT/$TTYD_PORT." >&2
  elif out=$(tailscale serve --bg --https="$HTTPS_PORT" "http://127.0.0.1:$SERVERJACK_PORT" 2>&1) \
     && out2=$(tailscale serve --bg --https="$HTTPS_PORT" --set-path="$mount" "http://127.0.0.1:$TTYD_PORT" 2>&1); then
    tailscale serve status | sed 's/^/  /'
    host=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
    hostport=$host; [[ $HTTPS_PORT != 443 ]] && hostport=$host:$HTTPS_PORT
    [[ -n "$host" ]] && say "Open: https://$hostport/"
  else
    echo "${out:-} ${out2:-}" | grep -qi "denied" \
      && todo+=("sudo tailscale set --operator=$USER   # then re-run install.sh: serve without sudo.
   NOTE: --operator takes ONE username for the whole machine. If another account
   already has it, either leave serve to that account (install.sh --no-serve) or
   run the serve commands with sudo from this one.") \
      || { echo "tailscale serve failed:"; echo "${out:-}"; echo "${out2:-}"; }
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
