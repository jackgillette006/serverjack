#!/usr/bin/env bash
# tmux session picker -- what ttyd runs for every browser connection.
#
#   Menu of tmux sessions (fzf) -> pick one -> attached. Detach (prefix d)
#   comes back to the menu instead of closing the tab. "New session" asks for
#   a name; typing a name that matches nothing and pressing Enter also creates
#   it. Esc / Ctrl-C / "Exit" ends the connection.
#
#   "New Claude Code session" / "New Codex session": asks for a name and a
#   directory (fzf over ~/workspace dirs, or type any path), then starts the
#   tool in a fresh tmux session there and attaches. The tool runs in front of
#   a login shell, so if it isn't installed or isn't logged in you land on the
#   error message and a prompt instead of the session silently vanishing.
#
# Fallback UI: used when ttyd is opened without a session argument (i.e. not
# via the tmux-web page). Needs fzf. Talks to your normal tmux server, so the
# sessions here are the same ones "tmux ls" shows anywhere else.
#
# Try it locally without ttyd:  bash bin/tmux-picker.sh

set -uo pipefail

export PATH="$HOME/.local/bin:$PATH"
export TERM="${TERM:-xterm-256color}"
command -v fzf >/dev/null || { echo "tmux-picker needs fzf (install.sh puts it in ~/.local/bin)"; sleep 5; exit 1; }

NEW=$'+\t+  New session'
NEW_CLAUDE=$'c\t>  New Claude Code session'
NEW_CODEX=$'o\t>  New Codex session'
EXIT=$'x\tx  Exit'

# Directories offered by the picker for new coding sessions (typing any other
# path works too).
IFS=: read -r -a DIR_ROOTS <<<"${TMUX_WEB_DIRS:-$HOME/projects:$HOME/src:$HOME/workspace:$HOME}"
DIR_ROOTS=("${DIR_ROOTS[@]/#\~/$HOME}")

list_sessions() {
  # name <TAB> padded-name + details -- fzf displays field 2, we act on field 1.
  # (%H.%M not %H:%M -- a colon inside #{t/f/...} terminates the format.)
  tmux list-sessions \
    -F '#{session_name}	#{p16:session_name} #{session_windows}w  #{?session_attached,attached,-       }  since #{t/f/%b %d %H.%M:session_created}' \
    2>/dev/null
}

attach() {
  # No "exec": returning here after detach is the whole point.
  # No "-d": don't yank the session away from a physical/SSH client.
  tmux attach-session -t "$1"
}

new_session() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    printf 'Session name (blank = auto): '
    IFS= read -r name || return 0
  fi
  if [[ -n "$name" ]]; then
    # -A: if it already exists, just attach to it rather than failing.
    tmux new-session -A -s "$name" -c "$HOME"
  else
    tmux new-session -c "$HOME"
  fi
}

# Prompt for a session name on the tty; prints it, or nothing if blank/cancelled.
ask_name() {
  local name
  printf '%s' "$1" >/dev/tty
  IFS= read -r name </dev/tty || return 1
  [[ -n "$name" ]] || return 1
  if [[ "$name" == *[:.]* ]]; then
    echo "tmux session names can't contain ':' or '.'" >&2; sleep 2; return 1
  fi
  if tmux has-session -t "=$name" 2>/dev/null; then
    echo "a session called '$name' already exists" >&2; sleep 2; return 1
  fi
  printf '%s\n' "$name"
}

# fzf over likely project dirs, or a typed path. Prints the chosen absolute dir.
pick_dir() {
  local out rc query sel dir
  out=$( { printf '%s\n' "${DIR_ROOTS[@]}"
           find "${DIR_ROOTS[@]}" -mindepth 1 -maxdepth 1 -type d ! -name '.*' 2>/dev/null
         } | sort -u |
    fzf --print-query --reverse --no-multi --cycle \
        --prompt='directory > ' \
        --header='Enter: pick   or type any path + Enter   Esc: cancel' \
        --info=inline --height=100% )
  rc=$?
  (( rc == 130 )) && return 1
  query=$(printf '%s\n' "$out" | sed -n 1p)
  sel=$(printf '%s\n' "$out" | sed -n 2p)
  dir="${sel:-$query}"
  dir="${dir/#\~/$HOME}"
  [[ -n "$dir" ]] || return 1
  if [[ ! -d "$dir" ]]; then
    echo "no such directory: $dir" >&2; sleep 2; return 1
  fi
  ( cd "$dir" && pwd -P )
}

# $1 = command to run (claude | codex), $2 = label for prompts
new_code_session() {
  local tool="$1" label="$2" name dir
  name=$(ask_name "$label session name: ") || return 0
  dir=$(pick_dir) || return 0
  # The tool runs first; when it exits (normally, not installed, not logged
  # in, crashed) its output stays on screen and you get a shell in the same
  # dir. -e PATH: a tmux server started from a tty1 login may not have
  # ~/.local/bin, which is where claude lives.
  tmux new-session -d -s "$name" -n "$tool" -c "$dir" -e PATH="$PATH" \
    "$tool; rc=\$?; echo; echo \"[$tool exited with status \$rc]\"; exec bash -l"
  attach "$name"
}

while true; do
  # --print-query gives us "query\nselection"; selection is empty when nothing
  # matched, which is how "type a new name + Enter" creates a session.
  out=$( { list_sessions; printf '%s\n' "$NEW" "$NEW_CLAUDE" "$NEW_CODEX" "$EXIT"; } |
    fzf --print-query --reverse --no-multi --cycle \
        --delimiter='\t' --with-nth=2 \
        --prompt="$(hostname -s) tmux > " \
        --header='Enter: attach   type a new name + Enter: create   Esc: close' \
        --info=inline --height=100% )
  rc=$?

  query=$(printf '%s\n' "$out" | sed -n 1p)
  pick=$(printf '%s\n' "$out" | sed -n 2p)

  if (( rc == 130 )); then        # Esc / Ctrl-C
    exit 0
  elif (( rc == 1 )); then        # no match -> treat the query as a new name
    [[ -n "$query" ]] && new_session "$query"
    continue
  elif (( rc != 0 )); then
    exit "$rc"
  fi

  case "$pick" in
    "$EXIT")       exit 0 ;;
    "$NEW")        new_session ;;
    "$NEW_CLAUDE") new_code_session claude "Claude Code" ;;
    "$NEW_CODEX")  new_code_session codex  "Codex" ;;
    *)       attach "${pick%%$'\t'*}" ;;
  esac
done
