#!/usr/bin/env bash
# One serverjack + serverjack-ttyd pair that a browser test can restart, for
# pwchrome.py's "the terminal reconnects on its own" checks. The browser runs
# in a container and cannot signal host processes, so it asks through files:
#
#   bash tests/restartable.sh CTL_DIR BASE_URL     (environment = the instance's)
#
#   CTL_DIR/req    the test writes "web|ttyd|both <seconds down>" (via a
#                  rename, so it is never read half-written)
#   CTL_DIR/state  "down N" once request N has stopped what it named,
#                  "up N" once BASE_URL/term/token answers again
#
# Stopping is a plain SIGTERM, which is what `systemctl --user restart` sends.
set -uo pipefail
ctl=${1:?CTL_DIR} base=${2:?BASE_URL}
here=$(dirname "$(readlink -f "$0")")
logs=${RS_LOGS:-$here/shots}
web='' ttyd='' n=0

start_web()  { python3 "$here/../bin/serverjack" >>"$logs/web-rs.log" 2>&1 & web=$!; }
start_ttyd() { bash "$here/../bin/serverjack-ttyd" >>"$logs/ttyd-rs.log" 2>&1 & ttyd=$!; }
stop() { if [[ -n $1 ]]; then kill "$1" 2>/dev/null; wait "$1" 2>/dev/null; fi; return 0; }
ready() {
  local _
  for _ in $(seq 1 100); do
    curl -sf -o /dev/null "$base/term/token" && return 0
    sleep 0.1
  done
  return 1
}
trap 'stop "$web"; stop "$ttyd"; exit 0' TERM INT

start_web; start_ttyd
ready || echo "restartable.sh: instance did not come up (see $logs/web-rs.log)" >&2
echo "up 0" > "$ctl/state"
while sleep 0.1; do
  [[ -f $ctl/req ]] || continue
  read -r what secs < "$ctl/req" || true
  rm -f -- "$ctl/req"
  n=$((n + 1))
  case $what in web|both) stop "$web" ;; esac
  case $what in ttyd|both) stop "$ttyd" ;; esac
  echo "down $n" > "$ctl/state"
  sleep "${secs:-0}"
  case $what in web|both) start_web ;; esac
  case $what in ttyd|both) start_ttyd ;; esac
  ready || echo "restartable.sh: instance did not come back after request $n" >&2
  echo "up $n" > "$ctl/state"
done
