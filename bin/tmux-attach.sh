#!/usr/bin/env bash
# ttyd's command. The landing page (bin/serverjack) sends the browser to
# /term/?arg=<session> and ttyd (-a) turns that into "$1" here.
#
#   with an argument : attach to exactly that tmux session
#   no argument      : fall back to the fzf picker (tmux-picker.sh)
#
# Anything reaching this script is already inside the tailnet trust boundary;
# the argument is only ever used as a tmux session name, never executed.

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export TERM="${TERM:-xterm-256color}"

if [[ $# -eq 0 ]]; then
  exec bash "$(dirname "$(readlink -f "$0")")/tmux-picker.sh"
fi

name="$1"
if ! tmux has-session -t "=$name" 2>/dev/null; then
  printf '\n  No tmux session called "%s" (it may have exited).\n' "$name"
  printf '  Go back to the session list to pick another.\n\n'
  # Long pause: ttyd auto-reconnects (re-running this) when we exit, and the
  # web page moves you to another session within ~15s on its own.
  sleep 20
  exit 1
fi

# No -d: never yank the session away from another client (tty1, ssh, phone).
exec tmux attach-session -t "=$name"
