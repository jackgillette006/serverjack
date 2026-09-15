#!/usr/bin/env bash
# Remove serverjack's user units, its runtime sockets and its tailscale serve
# entries. Leaves ~/.local/bin binaries, ~/.config/serverjack (env,
# shortcuts.json, tools.json) and your tmux sessions alone -- delete those
# yourself if you want them gone. The one exception is
# ~/.config/serverjack/install-path: that is not your data, only a record of
# where a git checkout lives for channel detection, and leaving it behind
# used to let a later `serverjack-ctl update` resurrect an already-
# uninstalled checkout instead of refusing.
set -uo pipefail
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
UNIT_DIR=$HOME/.config/systemd/user
SELF_DIR_FOR_LIB=$(cd "$(dirname "$(readlink -f "$0")")" 2>/dev/null && pwd || true)
# shellcheck source=bin/serverjack-lib.sh
[[ -n $SELF_DIR_FOR_LIB && -f "$SELF_DIR_FOR_LIB/bin/serverjack-lib.sh" ]] \
  && source "$SELF_DIR_FOR_LIB/bin/serverjack-lib.sh"

# A copy of this file inside a managed release
# (~/.local/share/serverjack/releases/<v>/uninstall.sh) run BY HAND (not via
# serverjack-ctl, which sets SERVERJACK_CTL_MANAGED and knows to also clean
# up ~/.local/share/serverjack/install.json and the release tree afterward)
# would remove the units but leave install.json pointing at a release whose
# units it just deleted -- the bootstrap would then see that as an existing
# install and refuse to reinstall, and serverjack-ctl would report a channel
# that no longer has any units. Refuse and point at the helper that handles
# all of that instead of duplicating its bookkeeping here.
if [[ -z ${SERVERJACK_CTL_MANAGED:-} ]]; then
  SHARE_RELEASES_REAL=$(readlink -f "$HOME/.local/share/serverjack/releases" 2>/dev/null || true)
  SELF_DIR=$(cd "$(dirname "$(readlink -f "$0")")" 2>/dev/null && pwd || true)
  if [[ -n $SHARE_RELEASES_REAL && -n $SELF_DIR ]]; then
    case "$SELF_DIR" in
      "$SHARE_RELEASES_REAL"/*)
        cat >&2 <<EOF
This uninstall.sh is inside a managed release ($SELF_DIR).

Running it directly would remove the units but leave
$HOME/.local/share/serverjack/install.json pointing at a release that no
longer has any -- a later bootstrap run would then see a phantom install and
refuse to reinstall. Use the lifecycle helper instead, which also asks for
confirmation and cleans up $HOME/.local/share/serverjack properly:
  ~/.local/bin/serverjack-ctl uninstall
EOF
        exit 1
        ;;
    esac
  fi
fi

systemctl --user disable --now serverjack serverjack-ttyd 2>/dev/null
rm -f "$UNIT_DIR"/serverjack.service "$UNIT_DIR"/serverjack-ttyd.service

systemctl --user daemon-reload

# The sockets live in the runtime dir. The directory itself is left: the other
# unit of a *second* instance may still be using it. "secret" is from the old
# token scheme and no longer written; removed here so it does not linger.
RUNTIME=${XDG_RUNTIME_DIR}/serverjack
rm -f "$RUNTIME/web.sock" "$RUNTIME/ttyd.sock" "$RUNTIME/secret"

if command -v tailscale >/dev/null 2>&1; then
  # `tailscale serve` is machine-wide. Inspect each mapping and remove it only
  # when its backend exactly matches this account's configured loopback port
  # or private runtime socket. A foreign path on the same HTTPS listener stays.
  ENV_FILE=$HOME/.config/serverjack/env
  env_get() {
    local key=$1 line value=
    [[ -f $ENV_FILE && ! -L $ENV_FILE ]] || return 0
    while IFS= read -r line || [[ -n $line ]]; do
      [[ $line == "$key="* ]] && value=${line#*=}
    done < "$ENV_FILE"
    value=${value#\"}; value=${value%\"}
    printf '%s' "$value"
  }
  mount=$(env_get SERVERJACK_TERM);       mount=${mount:-/term/}; mount=${mount%/}
  https=$(env_get SERVERJACK_HTTPS_PORT); https=${https:-443}
  port=$(env_get SERVERJACK_PORT);        port=${port:-7680}
  legacy_port=$(env_get TTYD_PORT)

  config_ok=1
  [[ $https =~ ^(443|8443|10000)$ ]] || config_ok=0
  [[ $port =~ ^[0-9]{1,5}$ ]] \
    && (( 10#$port >= 1 && 10#$port <= 65535 )) || config_ok=0
  [[ $mount =~ ^/[A-Za-z0-9._~/-]+$ && $mount != / ]] || config_ok=0
  if [[ -n $legacy_port ]]; then
    if [[ $legacy_port =~ ^[0-9]{1,5}$ ]] \
        && (( 10#$legacy_port >= 1 && 10#$legacy_port <= 65535 )); then
      legacy_port=$((10#$legacy_port))
    else
      legacy_port=
    fi
  fi

  if (( ! config_ok )); then
    echo "tailscale serve routes left unchanged: serverjack's saved port, HTTPS port or terminal path is invalid" >&2
  elif ! serve_status=$(tailscale serve status 2>/dev/null); then
    echo "tailscale serve routes left unchanged: could not inspect the current serve status" >&2
  else
    port=$((10#$port))
    own_backends=("http://127.0.0.1:$port" "unix:$RUNTIME/web.sock" "unix:$RUNTIME/ttyd.sock")
    [[ -n $legacy_port ]] && own_backends+=("http://127.0.0.1:$legacy_port")
    # remove_owned_mapping/serve_backends_for/backend_is_ours: bin/serverjack-lib.sh
    # (A11) -- ONE implementation, shared with bin/serverjack-ctl's
    # remove_units_and_serve_route() and bin/serverjack-setup, instead of
    # three drifting copies of the same parsing and removal logic.
    remove_owned_mapping "https=$https path=/" "$serve_status" "$https" / "${own_backends[@]}"
    remove_owned_mapping "https=$https path=$mount" "$serve_status" "$https" "$mount" "${own_backends[@]}"
  fi
fi
# Not part of "your data" this deliberately keeps (env, shortcuts.json,
# tools.json) -- it is only serverjack-ctl's/serverjack-setup's own record
# of where a git checkout lives, read by detect_channel()/resolve_self() to
# decide whether THIS looks like a live install. Leaving it behind used to
# let `serverjack-ctl update` "succeed" by resurrecting an already-
# uninstalled checkout with a fresh `git pull && bash install.sh` instead of
# refusing -- see cmd_update()'s own no-units check in bin/serverjack-ctl,
# the other half of this fix (finding 15).
rm -f "$HOME/.config/serverjack/install-path"

echo "removed. tmux sessions were not touched."
