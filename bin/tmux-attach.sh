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

# Targets end in ':' (the session's current window): tmux reads an argument
# ending in ';' as a command separator, so "=x;" asked about session "x" --
# and attached to it, if there was one.
if ! tmux has-session -t "=$name:" 2>/dev/null; then
  printf '\n  No tmux session called "%s" (it may have exited).\n' "$name"
  printf '  Go back to the session list to pick another.\n\n'
  sleep 20
  exit 1
fi

# What the page changes on a session while it has it open. Once no page has
# the session open any more, restore() puts back exactly what was there
# before -- tmux's own default, or a value you set on that session or
# window yourself -- so an ssh or tty1 client sees its usual tmux again as
# soon as the browser has gone:
#
# - status off. The page has its own bar (tabs, window count), so tmux's
#   status line is just noise in a browser. It is a session option -- tmux
#   has no per-client status line -- so an ssh client attached at the same
#   time as the page loses it too, for as long as the page is open.
#   SERVERJACK_TMUX_STATUS=on leaves the status line alone.
# - fill-character ' ', whatever SERVERJACK_TMUX_STATUS says. When two
#   clients of different sizes share a window (a phone and a desktop), the
#   bigger one shows the window in its corner and tmux fills the rest with
#   '·' dots, a screenful of what looks like garbage. Blank space says the
#   same thing quietly. A window option, tmux >= 3.3 (older ones don't have
#   it, and it is skipped), so every window gets it, and a hook gives it to
#   windows made while the page is open.
#
# The bookkeeping is in tmux user options. @serverjack_status (on the
# session) and @serverjack_fill (on each window) hold what was there before:
# "u" for nothing set, "=<value>" for a value of yours. @serverjack_pages
# lists the pids of the copies of this script that have the session open.
# They are only ever read and changed under one lock, so a page that opens
# just as another closes can't have its changes undone by the other's
# restore() halfway through.
sid=$(tmux display -p -t "=$name:" '#{session_id}' 2>/dev/null) || sid=
lockfile=$base/serverjack/attach.lock
lk=
# One line per window: its id, 1 if its fill-character is our blank right
# now, and what @serverjack_fill saved for it (empty: not ours). Values are
# read back with `tmux -u`: without a UTF-8 locale (ttyd's environment need
# not have one) tmux turns the tabs, and any non-ASCII fill-character, into
# '_' in what it prints.
wins_fmt=$'#{window_id}\t#{?#{==:#{fill-character}, },1,0}\t#{@serverjack_fill}'

# flock is util-linux's, a prerequisite of bin/serverjack-setup; without it
# this runs unlocked. The lock is held for a few tmux calls at a time, and
# one still held after 3 s (a hung tmux server) is ignored rather than
# leaving the page blank. A dead holder's lock goes with it.
lock() {
  command -v flock >/dev/null || return 0
  exec {lk}>>"$lockfile" || return 0
  flock -w 3 "$lk" || :
} 2>/dev/null

unlock() {
  [[ -n $lk ]] || return 0
  exec {lk}>&-
  lk=
}

# The other pids in @serverjack_pages, each only while it is still a running
# tmux-attach.sh: a copy killed outright never takes itself off the list.
others() {
  local p
  for p in $(tmux show-options -qv -t "$sid" @serverjack_pages); do
    [[ $p =~ ^[0-9]+$ && $p != "$$" ]] || continue
    [[ $(tr '\0' ' ' < "/proc/$p/cmdline") == *tmux-attach.sh* ]] && printf '%s ' "$p"
  done
} 2>/dev/null

# A page attached by an older copy of this script, which exec'd tmux and so
# is not on the list: a client of the session whose parent is ttyd itself.
# ssh, tty1 and desktop terminals don't count -- they are who restore() is
# for.
old_page() {
  local pid stat ppid
  while read -r pid; do
    [[ $pid =~ ^[0-9]+$ ]] || continue
    read -r stat < "/proc/$pid/stat" || continue
    stat=${stat##*) }               # drop "pid (comm) ": comm can hold spaces
    ppid=${stat#* }
    ppid=${ppid%% *}
    [[ $ppid =~ ^[0-9]+$ && $(< "/proc/$ppid/comm") == ttyd ]] && return 0
  done < <(tmux list-clients -t "$sid" -F '#{client_pid}')
  return 1
} 2>/dev/null

# tmux takes an argument ending in ';' as the end of a command and '\;' as
# a literal ';' -- and a saved fill-character can be any character.
targ() {
  if [[ $1 == *';' ]]; then printf '%s\\;' "${1%;}"; else printf '%s' "$1"; fi
}

# Under the lock. Saves what is there unless it is saved already and still
# ours (the user may have changed it since), then sets ours.
apply() {
  local st mark w ours
  if [[ ${SERVERJACK_TMUX_STATUS:-off} != on ]]; then
    st=$(tmux show-options -qv -t "$sid" status)
    mark=$(tmux show-options -qv -t "$sid" @serverjack_status)
    if [[ -z $mark || $st != off ]]; then
      mark=u
      [[ -n $st ]] && mark="=$st"
    fi
    tmux set-option -t "$sid" @serverjack_status "$mark" \; set-option -t "$sid" status off
  fi
  tmux show-options -gw fill-character >/dev/null || return 0    # tmux < 3.3
  while IFS=$'\t' read -r w ours mark; do
    [[ -n $mark && $ours == 1 ]] && continue
    st=$(tmux -u show-options -wqv -t "$w" fill-character)
    mark=u
    [[ -n $st ]] && mark="=$st"
    tmux set-option -w -t "$w" @serverjack_fill "$(targ "$mark")" \; \
         set-option -w -t "$w" fill-character ' '
  done < <(tmux -u list-windows -t "$sid" -F "$wins_fmt")
  # An index of its own, so a user's own after-new-window hook is untouched.
  # A session-level hook array hides the global one, so a session with no
  # array of its own gets a copy of the global entries first (they keep
  # firing while the page is open), and @serverjack_hook says to drop the
  # whole array again when the last page leaves ("u"; "=" for an array of
  # the session's own, which keeps everything but [73]).
  if [[ -z $(tmux show-options -qv -t "$sid" @serverjack_hook) ]]; then
    if [[ -n $(tmux show-hooks -t "$sid" after-new-window) ]]; then
      mark='='
    else
      mark=u
      while IFS= read -r w; do
        [[ $w =~ ^after-new-window\[([0-9]+)\]\ (.*)$ ]] || continue
        [[ ${BASH_REMATCH[1]} == 73 ]] && continue
        tmux set-hook -t "$sid" "after-new-window[${BASH_REMATCH[1]}]" "${BASH_REMATCH[2]}"
      done < <(tmux show-hooks -g after-new-window)
    fi
    tmux set-option -t "$sid" @serverjack_hook "$mark"
  fi
  tmux set-hook -t "$sid" 'after-new-window[73]' \
       "set-option -w fill-character ' ' ; set-option -w @serverjack_fill u"
} 2>/dev/null

# Under the lock, with no page left. Puts back what apply() saved -- unless
# it was changed while the page was open, in which case that change stays.
undo() {
  local st mark w ours
  mark=$(tmux show-options -qv -t "$sid" @serverjack_status)
  if [[ -n $mark ]]; then
    st=$(tmux show-options -qv -t "$sid" status)
    if [[ $st != off ]]; then
      tmux set-option -u -t "$sid" @serverjack_status
    elif [[ $mark == =* ]]; then
      tmux set-option -t "$sid" status "${mark#=}" \; set-option -u -t "$sid" @serverjack_status
    else                    # unset, not "on": back to whatever tmux.conf says
      tmux set-option -u -t "$sid" status \; set-option -u -t "$sid" @serverjack_status
    fi
  fi
  while IFS=$'\t' read -r w ours mark; do
    [[ -n $mark ]] || continue
    if [[ $ours != 1 ]]; then
      tmux set-option -u -w -t "$w" @serverjack_fill
    elif [[ $mark == =* ]]; then
      tmux set-option -w -t "$w" fill-character "$(targ "${mark#=}")" \; \
           set-option -u -w -t "$w" @serverjack_fill
    else
      tmux set-option -u -w -t "$w" fill-character \; set-option -u -w -t "$w" @serverjack_fill
    fi
  done < <(tmux -u list-windows -t "$sid" -F "$wins_fmt")
  # Removing index 73 alone leaves an empty array behind, which still hides
  # the global hooks: for good, once the page has gone.
  mark=$(tmux show-options -qv -t "$sid" @serverjack_hook)
  if [[ $mark == u ]]; then
    tmux set-hook -u -t "$sid" after-new-window
  else
    tmux set-hook -u -t "$sid" 'after-new-window[73]'
    # no mark: a page from before the marks; an array with nothing left in it is ours
    [[ -z $mark && $(tmux show-hooks -t "$sid" after-new-window) != *'['* ]] &&
      tmux set-hook -u -t "$sid" after-new-window
  fi
  tmux set-option -u -t "$sid" @serverjack_hook
} 2>/dev/null

restore() {
  [[ -n $sid ]] || return 0
  local left
  lock
  left=$(others)
  if [[ -n $left ]]; then
    tmux set-option -t "$sid" @serverjack_pages "${left% }"
  else
    tmux set-option -u -t "$sid" @serverjack_pages
    old_page || undo
  fi
  unlock
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
# During the setup a hangup only marks this shell: the tmux calls and flock
# run in a subshell that ignores it, so they finish rather than stop
# halfway, and a page that is already gone is then not attached at all.
# ttyd keeps the terminal open until this script exits, so attaching after
# the hangup would leave a client attached for good that no page shows (and
# that takes the window's size).
# tmux runs in the background and is waited for, so the trap runs the moment
# a hangup comes (with tmux in the foreground it ran only once tmux had
# ended), and from then on this shell hangs tmux up itself until it goes.
# ttyd hangs up only once, and one that landed between the check below and
# tmux starting reached neither: this shell was past the check, and tmux was
# not there yet, or was a child just forked that still ran this shell's trap.
# So tmux stayed attached, and this shell waited on it, for good. Its input
# is the terminal, said explicitly: a background command's is /dev/null
# otherwise.
# No -d: never yank the session away from another client (tty1, ssh, phone).
hup=
trap 'hup=1' HUP
if [[ -n $sid ]]; then
  (
    trap '' HUP
    lock
    tmux set-option -t "$sid" @serverjack_pages "$(others)$$" 2>/dev/null
    apply
    unlock
  )
fi
rc=1
if [[ -z $hup ]]; then
  exec {tty}<&0
  tmux "${features[@]}" attach-session -t "${sid:-=$name:}" <&"$tty" {tty}<&- &
  client=$!
  exec {tty}<&-
  while kill -0 "$client" 2>/dev/null; do
    if [[ -n $hup ]]; then
      kill -HUP "$client" 2>/dev/null
      sleep 0.1
    else
      wait "$client"          # returns early when the trap fires
    fi
  done
  wait "$client"
  rc=$?
fi
exec >/dev/null 2>&1          # the terminal is gone; nothing to write to
restore
exit "$rc"
