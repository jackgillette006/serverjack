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
  # Long pause: ttyd auto-reconnects (re-running this) when we exit. The web
  # page notices a session that is gone and takes you to the session list.
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

# What the page changes on a session while it has it open. restore() below
# puts both back once no page has the session open any more, so an ssh or
# tty1 client sees plain tmux again as soon as the browser has gone:
#
# - status off. The page has its own bar (tabs, window count), so tmux's
#   status line is just noise in a browser. It is a session option -- tmux
#   has no per-client status line -- so an ssh client attached at the same
#   time as the page loses it too, for as long as the page is open.
#   SERVERJACK_TMUX_STATUS=on leaves it alone.
# - fill-character ' '. When two clients of different sizes share a window
#   (a phone and a desktop), the bigger one shows the window in its corner
#   and tmux fills the rest with '·' dots, a screenful of what looks like
#   garbage. Blank space says the same thing quietly. A window option, tmux
#   >= 3.3 (older ones refuse it, and it is skipped), so every window gets
#   it, and a hook gives it to windows made while the page is open.
#
# @serverjack_status and @serverjack_fill mark what this file set, so
# restore() only ever undoes its own changes.
sid=$(tmux display -p -t "=$name:" '#{session_id}' 2>/dev/null) || sid=
pre=()
if [[ -n $sid && "${SERVERJACK_TMUX_STATUS:-off}" != "on" ]]; then
  # Run in the same tmux command as the attach below, so a page that is just
  # leaving (restore() in another copy of this script) can't put the status
  # line back in between.
  pre=(set-option -t "$sid" status off \; set-option -t "$sid" @serverjack_status 1 \;)
fi
if [[ -n $sid ]] && tmux set-option -w -t "$sid:" fill-character ' ' 2>/dev/null; then
  tmux set-option -t "$sid" @serverjack_fill 1
  while read -r w; do
    tmux set-option -w -t "$w" fill-character ' '
  done < <(tmux list-windows -t "$sid" -F '#{window_id}')
  # An index of its own, so a user's own after-new-window hook is untouched.
  tmux set-hook -t "$sid" 'after-new-window[73]' "set-option -w fill-character ' '"
fi 2>/dev/null

# True while another serverjack page still has the session open: a client
# whose parent process is this script (ttyd runs tmux-attach.sh, which runs
# tmux) or, for a page attached by an older copy that exec'd tmux, ttyd
# itself. ssh, tty1 and desktop terminals don't count -- they are who
# restore() is for.
page_attached() {
  local pid stat ppid
  while read -r pid; do
    [[ $pid =~ ^[0-9]+$ ]] || continue
    read -r stat < "/proc/$pid/stat" || continue
    stat=${stat##*) }               # drop "pid (comm) ": comm can hold spaces
    ppid=${stat#* }
    ppid=${ppid%% *}
    [[ $ppid =~ ^[0-9]+$ ]] || continue
    [[ $(tr '\0' ' ' < "/proc/$ppid/cmdline") == *tmux-attach.sh* ||
       $(< "/proc/$ppid/comm") == ttyd ]] && return 0
  done < <(tmux list-clients -t "$sid" -F '#{client_pid}')
  return 1
} 2>/dev/null

restore() {
  [[ -n $sid ]] || return 0
  page_attached && return 0
  if [[ $(tmux show-options -qv -t "$sid" @serverjack_status) == 1 ]]; then
    # Unset, not "on": back to whatever the user's own tmux.conf says.
    tmux set-option -u -t "$sid" status \; set-option -u -t "$sid" @serverjack_status
  fi
  if [[ $(tmux show-options -qv -t "$sid" @serverjack_fill) == 1 ]]; then
    while read -r w; do
      tmux set-option -u -w -t "$w" fill-character
    done < <(tmux list-windows -t "$sid" -F '#{window_id}')
    tmux set-hook -u -t "$sid" 'after-new-window[73]' \; set-option -u -t "$sid" @serverjack_fill
  fi
} 2>/dev/null

# Truecolor. ttyd's terminal is xterm.js, which draws 24-bit colour, but
# nothing tells tmux that: TERM is xterm-256color, whose terminfo has no RGB
# flag, so tmux would quantise every 24-bit colour a program prints to the
# 256-colour palette before it reaches the browser. -T RGB says so for this
# client only; an ssh client of the same session keeps whatever its own
# terminal supports. It is a tmux >= 3.2 flag and an older tmux refuses to
# start at all with it, so probe first: no flag means 256 colours, as before.
features=()
tmux -T RGB -V >/dev/null 2>&1 && features=(-T RGB)

# Not exec'd, so restore() can run once the client has gone. When the page
# goes (tab closed, reload, dropped connection) ttyd hangs up this whole
# process group: tmux exits, and the trap keeps this shell alive to clean up.
# No -d: never yank the session away from another client (tty1, ssh, phone).
trap ':' HUP
tmux "${features[@]}" "${pre[@]}" attach-session -t "=$name"
rc=$?
exec >/dev/null 2>&1          # the terminal is gone; nothing to write to
restore
exit "$rc"
