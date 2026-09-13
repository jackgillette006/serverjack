#!/usr/bin/env bash
# Remove serverjack's user units, its runtime sockets and its tailscale serve
# entries. Leaves ~/.local/bin binaries, ~/.config/serverjack (env,
# shortcuts.json, tools.json) and your tmux sessions alone -- delete those
# yourself if you want them gone.
set -uo pipefail
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
UNIT_DIR=$HOME/.config/systemd/user

systemctl --user disable --now serverjack serverjack-ttyd 2>/dev/null
rm -f "$UNIT_DIR"/serverjack.service "$UNIT_DIR"/serverjack-ttyd.service

# Units from the pre-rename tmux-web install, if this machine still has them.
old=()
for u in tmux-web ttyd; do
  [[ -f "$UNIT_DIR/$u.service" ]] && old+=("$u")
done
if (( ${#old[@]} )); then
  systemctl --user disable --now "${old[@]}" 2>/dev/null
  for u in "${old[@]}"; do rm -f "$UNIT_DIR/$u.service"; done
  echo "also removed old tmux-web user units: ${old[*]}"
fi

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
    serve_backends_for() {
      local wanted_port=$1 wanted_path=$2
      awk -v wp="$wanted_port" -v wpath="$wanted_path" '
        /^https:\/\// { h=$1; sub(/^https:\/\//,"",h); n=split(h,a,":");
                        cur=(n>1 ? a[n] : "443"); next }
        /^\|--/ && cur==wp && $2==wpath { print $NF }' <<< "$serve_status"
    }
    backend_is_ours() {
      local backend=$1
      [[ $backend == "http://127.0.0.1:$port" \
         || $backend == "unix:$RUNTIME/web.sock" \
         || $backend == "unix:$RUNTIME/ttyd.sock" \
         || ( -n $legacy_port && $backend == "http://127.0.0.1:$legacy_port" ) ]]
    }
    remove_owned_mapping() {
      local path=$1 label=$2 backend
      local -a backends=()
      mapfile -t backends < <(serve_backends_for "$https" "$path")
      if (( ${#backends[@]} == 0 )); then
        return
      elif (( ${#backends[@]} != 1 )); then
        echo "tailscale serve $label left unchanged: status was ambiguous" >&2
        return
      fi
      backend=${backends[0]}
      if ! backend_is_ours "$backend"; then
        echo "tailscale serve $label left unchanged: it points to a foreign backend ($backend)" >&2
        return
      fi
      if tailscale serve --https="$https" --set-path="$path" off >/dev/null 2>&1; then
        echo "removed tailscale serve $label ($backend)"
      else
        echo "could not remove tailscale serve $label ($backend); it was left unchanged" >&2
      fi
    }
    remove_owned_mapping / "https=$https path=/"
    remove_owned_mapping "$mount" "https=$https path=$mount"
  fi
fi
echo "removed. tmux sessions were not touched."
