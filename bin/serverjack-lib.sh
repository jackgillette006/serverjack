# shellcheck shell=bash
# serverjack-lib.sh: small helpers shared by install.sh and bin/serverjack-setup
# (port/serve-clash detection, a local health poll). Sourced, never executed
# directly -- has no shebang and no `set -Eeuo pipefail` of its own on
# purpose, so it inherits whichever the sourcing script already has instead
# of silently changing it. Existed as two near-identical, drifting copies
# (install.sh and bin/serverjack-setup each had their own port_holder()/
# serve_backend_for()) before this; kept here as ONE copy so a fix to one
# (like the `|| true` guards below, each found the hard way) can't miss the
# other.

# True if nothing is listening on TCP port $1 (any interface, any account).
port_free() { ! ss -ltnp 2>/dev/null | grep -q ":$1 "; }

# Best-effort description of whatever IS listening on TCP port $1 --
# ss -ltnp shows a listener's process name for our own uid always, and for
# others' too only when this happens to run with enough privilege to see it;
# the port being busy is always detectable even when the owner can't be
# named. `|| true`: an unprivileged `ss` can't show another account's
# process info for a socket it doesn't own, so the final `grep -o`
# legitimately finds no "users:..." to print -- under `pipefail` that is a
# real non-zero pipeline exit, and every caller here assigns this plainly
# (`holder=$(port_holder ...)`, not inside `if`/`&&`), so under `set -e` an
# unguarded failure aborts the whole calling script silently, right before
# it can ever print the "port busy" message that was the entire point.
# Found by exactly that happening.
port_holder() { ss -ltnp 2>/dev/null | grep ":$1 " | grep -o 'users:.*' | head -1 || true; }

# Backend `tailscale serve` currently proxies <https port $1><path $2> to, as
# it prints it: "http://127.0.0.1:7680" or "unix:/run/user/1000/serverjack/web.sock".
# Empty when tailscale isn't installed, isn't up, or nothing is configured
# for that port+path. `|| true`: `tailscale serve status` legitimately exits
# non-zero when nothing is configured yet at all (the common case on a fresh
# account) -- under pipefail that fails this whole pipeline even though awk
# itself found nothing to print, and every caller assigns this plainly
# (`backend=$(serve_backend_for ...)`), so the same silent-abort-under-set-e
# bug as port_holder() applies here too. Found the same way.
serve_backend_for() {
  command -v tailscale >/dev/null 2>&1 || return 0
  tailscale serve status 2>/dev/null | awk -v wp="$1" -v wpath="$2" '
    /^https:\/\// { h=$1; sub(/^https:\/\//,"",h); n=split(h,a,":");
                    cur=(n>1 ? a[n] : "443"); next }
    /^\|--/ && cur==wp && $2==wpath { print $NF; exit }' || true
}

# HTTP status code for one request, as a single clean string ("000" if curl
# couldn't even connect, matching curl's own convention for that case).
# Extra args are passed straight to curl (a URL, --unix-socket SOCK, ...).
# Deliberately NOT `curl ... -w '%{http_code}' ... || echo 000`: curl's own
# -w output ALREADY prints "000" on a connection failure, and curl ALSO
# exits non-zero in that case, so chaining `|| echo 000` after it printed a
# SECOND "000" right after the first with no separator -- a failed check
# silently became the six-character string "000000", never "000". Found by
# exactly that happening.
local_http_code() {
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' "$@" 2>/dev/null)
  printf '%s' "${code:-000}"
}

# Polls local_http_code() (same "$@") once a second for up to $1 seconds;
# returns 0 the moment it sees "200", 1 if the timeout elapses. Used for the
# final health check in both bin/serverjack-setup and install.sh -- a single
# immediate curl right after `systemctl restart` raced the app's own startup
# time and could report failure on an install that was actually fine a
# moment later.
wait_local_healthz() {  # $1 = timeout seconds, $2.. = curl args (as local_http_code)
  local timeout=$1; shift
  local deadline=$((SECONDS + timeout)) code
  while (( SECONDS < deadline )); do
    code=$(local_http_code "$@")
    [[ $code == 200 ]] && return 0
    sleep 1
  done
  return 1
}
