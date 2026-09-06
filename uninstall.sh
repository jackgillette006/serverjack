#!/usr/bin/env bash
# Remove tmux-web's user units and tailscale serve entries. Leaves ~/.local/bin
# binaries and ~/.config/tmux-web/env in place (delete them yourself if wanted).
set -uo pipefail
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
systemctl --user disable --now tmux-web ttyd 2>/dev/null
rm -f ~/.config/systemd/user/{tmux-web,ttyd}.service
systemctl --user daemon-reload
if command -v tailscale >/dev/null 2>&1; then
  mount=$(grep -E '^TMUX_WEB_TERM=' ~/.config/tmux-web/env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'); mount=${mount:-/term/}
  tailscale serve --https=443 off 2>/dev/null
  tailscale serve --https=443 --set-path="${mount%/}" off 2>/dev/null
fi
echo "removed. tmux sessions were not touched."
