#!/usr/bin/env bash
# serverjack installer. NO sudo. Idempotent -- re-run after pulling changes.
#
#   bash install.sh              install/refresh and (re)start
#   bash install.sh --no-serve   skip the tailscale serve step
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
NO_SERVE=0; [[ "${1:-}" == "--no-serve" ]] && NO_SERVE=1

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
SERVERJACK_PORT=7680
TTYD_PORT=7681
SERVERJACK_TITLE=$(hostname -s)
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
SERVERJACK_PORT=$(cfg SERVERJACK_PORT 7680)
TTYD_PORT=$(cfg TTYD_PORT 7681)
SERVERJACK_TERM=$(cfg SERVERJACK_TERM /term/)

# ---------------------------------------------------------------- units
for u in serverjack serverjack-ttyd; do
  sed "s|@REPO@|$REPO|g" "systemd/$u.service" > "$UNIT_DIR/$u.service"
done
systemctl --user daemon-reload

# refuse to fight another process for the ports (e.g. an older system-level install)
for port in "$SERVERJACK_PORT" "$TTYD_PORT"; do
  if ss -ltnp 2>/dev/null | grep -q ":$port " && ! systemctl --user is-active --quiet serverjack serverjack-ttyd 2>/dev/null; then
    holder=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -o 'users:.*' | head -1)
    echo "port $port is already in use by something that isn't our user unit: $holder" >&2
    if [[ -f /etc/systemd/system/tmux-web.service || -f /etc/systemd/system/ttyd.service ]]; then
      echo "That looks like the old system-level tmux-web install. Remove it once (needs root):" >&2
      echo "  sudo systemctl disable --now tmux-web ttyd; sudo rm -f /etc/systemd/system/{tmux-web,ttyd}.service; sudo systemctl daemon-reload" >&2
    fi
    echo "then re-run: bash $REPO/install.sh" >&2
    exit 1
  fi
done

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
  say "Publishing on the tailnet (tailscale serve, HTTPS 443, tailnet only)"
  mount=${SERVERJACK_TERM%/}
  if out=$(tailscale serve --bg --https=443 "http://127.0.0.1:$SERVERJACK_PORT" 2>&1) \
     && out2=$(tailscale serve --bg --https=443 --set-path="$mount" "http://127.0.0.1:$TTYD_PORT" 2>&1); then
    tailscale serve status | sed 's/^/  /'
    host=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
    [[ -n "$host" ]] && say "Open: https://$host/"
  else
    echo "$out $out2" | grep -qi "denied" \
      && todo+=("sudo tailscale set --operator=$USER   # then re-run install.sh: serve without sudo") \
      || { echo "tailscale serve failed:"; echo "$out"; echo "$out2"; }
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
