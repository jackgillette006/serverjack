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
  # `tailscale serve` is machine-wide. Only ever turn off the HTTPS port THIS
  # account installed on -- another user's serverjack may own a different one.
  env_get() { grep -E "^$1=" "$HOME/.config/serverjack/env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'; }
  mount=$(env_get SERVERJACK_TERM);      mount=${mount:-/term/}
  https=$(env_get SERVERJACK_HTTPS_PORT); https=${https:-443}
  # One mount these days: "/" -> serverjack, which serves the terminal itself.
  # The --set-path line is only for installs made before that change, which
  # also published <mount> -> ttyd; it is a no-op otherwise.
  echo "turning off tailscale serve on https=$https (/)"
  tailscale serve --https="$https" off 2>/dev/null
  tailscale serve --https="$https" --set-path="${mount%/}" off 2>/dev/null
fi
echo "removed. tmux sessions were not touched."
