#!/usr/bin/env bash
# ttyd's command. The landing page (bin/serverjack) sends the browser to
# /term/?arg=<session>&arg=<token> and ttyd (-a) turns those into "$1" and
# "$2" here.
#
# A valid token is ALWAYS required. It is HMAC-SHA256(<runtime dir>/secret,
# name)[:32], minted by bin/serverjack and recomputed here by
# bin/serverjack-token. ttyd has no idea who is on the other end of its socket,
# so the token is the only thing separating "the page sent you" from "you typed
# ttyd's URL": without it, another account on this machine could open ttyd's
# port, and a tailnet device that SERVERJACK_ALLOW turned away with a 403 could
# walk straight around it.
#
# That also means there is no no-argument fallback any more --
# bin/tmux-picker.sh is still in the repo (run it yourself in a terminal if you
# like it) but nothing reaches it through the browser.
#
# The argument is only ever used as a tmux session name, never executed.

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export TERM="${TERM:-xterm-256color}"
here=$(dirname "$(readlink -f "$0")")

refuse() {
  printf '\n  %s\n\n' "$1"
  # Long pause: ttyd auto-reconnects (re-running this) when we exit, and the
  # web page moves you to another session within ~15s on its own.
  sleep 20
  exit 1
}

name="${1:-}"
token="${2:-}"
if [[ -z $name || -z $token ]] || ! python3 "$here/serverjack-token" "$name" "$token"; then
  refuse "Open this session from the serverjack page."
fi

if ! tmux has-session -t "=$name" 2>/dev/null; then
  printf '\n  No tmux session called "%s" (it may have exited).\n' "$name"
  printf '  Go back to the session list to pick another.\n\n'
  sleep 20
  exit 1
fi

# No -d: never yank the session away from another client (tty1, ssh, phone).
exec tmux attach-session -t "=$name"
