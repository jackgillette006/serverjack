#!/usr/bin/env bash
# ttyd's command. The terminal page loads /term/?arg=<session>, bin/serverjack
# proxies that to ttyd, and ttyd (-a) turns the argument into "$1" here.
#
# There is no authentication in this file and none is needed: ttyd listens only
# on <runtime dir>/ttyd.sock, inside a 0700 directory, and the one thing that
# connects to it is bin/serverjack -- which has already checked the connection's
# owner, the Host, and SERVERJACK_ALLOW. Nothing else on the machine or the
# tailnet can reach it, so there is nothing left here to prove.
#
# No no-argument fallback: bin/tmux-picker.sh is still in the repo (run it
# yourself in a terminal if you like it) but nothing reaches it this way.
#
# The argument is only ever used as a tmux session name, never executed.

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export TERM="${TERM:-xterm-256color}"

# The runtime dir this terminal was reached through must be ours: a real
# directory, not a symlink, owned by us, mode 0700. Same rule as
# bin/serverjack's safe_dir() and bin/serverjack-ttyd's check_dir(). Fails
# closed. (Belt and braces -- ttyd already refused to bind an unsafe one.)
check_dir() {
  local d=$1 what=$2 owner mode
  [[ -L $d ]] && { echo "serverjack: $what $d is a symlink -- refusing" >&2; return 1; }
  [[ -d $d ]] || { echo "serverjack: $what $d is not a directory -- refusing" >&2; return 1; }
  read -r owner mode < <(stat -c '%u %a' "$d") || return 1
  [[ $owner == "$(id -u)" ]] || {
    echo "serverjack: $what $d is owned by uid $owner, not $(id -u) -- refusing" >&2; return 1; }
  [[ $mode == 700 ]] || {
    chmod 700 "$d" 2>/dev/null || { echo "serverjack: $what $d is mode $mode, not 0700" >&2; return 1; }
    read -r owner mode < <(stat -c '%u %a' "$d")
    [[ $mode == 700 ]] || { echo "serverjack: $what $d is mode $mode, not 0700" >&2; return 1; }
  }
  return 0
}

refuse() {
  printf '\n  %s\n\n' "$1"
  # Long pause: ttyd auto-reconnects (re-running this) when we exit, and the
  # web page moves you to another session within ~15s on its own.
  sleep 20
  exit 1
}

base=${XDG_RUNTIME_DIR:-/tmp/serverjack-$(id -u)}
if [[ -z ${XDG_RUNTIME_DIR:-} ]]; then
  check_dir "$base" "runtime dir parent" || refuse "The serverjack runtime directory is not safe to use."
fi
check_dir "$base/serverjack" "runtime dir" || refuse "The serverjack runtime directory is not safe to use."

name="${1:-}"
if [[ -z $name ]]; then
  refuse "Open a session from the serverjack page."
fi

if ! tmux has-session -t "=$name" 2>/dev/null; then
  printf '\n  No tmux session called "%s" (it may have exited).\n' "$name"
  printf '  Go back to the session list to pick another.\n\n'
  sleep 20
  exit 1
fi

# No -d: never yank the session away from another client (tty1, ssh, phone).
exec tmux attach-session -t "=$name"
