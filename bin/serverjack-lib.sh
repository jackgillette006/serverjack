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

# Same parsing as serve_backend_for(), but against an ALREADY-CAPTURED
# `tailscale serve status` text (so a caller removing more than one mapping
# -- see remove_owned_mapping() below -- reads one consistent snapshot
# instead of one status call per mapping, which could observe a config
# change made between the two) and returns EVERY matching backend, one per
# line, not just the first: remove_owned_mapping() needs the count to tell
# an unambiguous mapping from an ambiguous one, which serve_backend_for()'s
# early `exit` can't report.
serve_backends_for() {  # $1 https-port  $2 path  $3 `tailscale serve status` text
  awk -v wp="$1" -v wpath="$2" '
    /^https:\/\// { h=$1; sub(/^https:\/\//,"",h); n=split(h,a,":");
                    cur=(n>1 ? a[n] : "443"); next }
    /^\|--/ && cur==wp && $2==wpath { print $NF }' <<<"$3"
}

# True if $1 (a backend string exactly as `tailscale serve status` prints
# it, e.g. "http://127.0.0.1:7680" or "unix:/run/user/1000/serverjack/web.sock")
# is one of THIS installation's own backends, given as $2... by the caller
# (each caller knows its own port/socket paths; this only compares). Used
# before treating an existing serve mapping as a clash, and before removing
# one -- a mapping that is already ours (this account's own port or Unix
# socket, from an earlier run) is never a foreign clash, and remove_owned_
# mapping() below must never remove anything else. Existed as install.sh's
# own private copy before this (A1: bin/serverjack-setup's check_serve_clash()
# had no equivalent at all, so it flagged this account's own already-
# published mapping as foreign on every rerun).
backend_is_ours() {
  local backend=$1; shift
  local b
  for b in "$@"; do [[ $backend == "$b" ]] && return 0; done
  return 1
}

# Removes one tailscale serve mapping (<https port> <path>) if, and only if,
# it exists, is unambiguous, and is one of this installation's own backends
# ($5... -- see backend_is_ours()). Otherwise leaves it exactly alone and
# says why, with the command to inspect it by hand. Returns 0 when the
# mapping is gone afterward (removed just now, or never existed) and 1 when
# something is still there (foreign, ambiguous, or the `tailscale serve ...
# off` call itself failed) -- a caller that must know whether the route is
# REALLY gone (not just that this printed something) checks the exit status,
# not only the message (A11: uninstall's final summary must not always
# claim success). One `tailscale serve status` capture ($2) is expected to
# be shared across every mapping a caller removes in one run (backup_
# current_state()-style callers do two: "/" and the legacy /term mount) --
# passed in rather than captured here, so removing several mappings reads
# one consistent snapshot instead of racing itself across separate calls.
remove_owned_mapping() {  # $1 label  $2 status-text  $3 https-port  $4 path  $5.. own backends
  local label=$1 status=$2 https=$3 path=$4; shift 4
  local -a own=("$@")
  local -a backends=()
  mapfile -t backends < <(serve_backends_for "$https" "$path" "$status")
  if (( ${#backends[@]} == 0 )); then
    return 0
  elif (( ${#backends[@]} != 1 )); then
    echo "tailscale serve $label left in place: status was ambiguous -- run \`tailscale serve status\` to inspect it" >&2
    return 1
  fi
  local backend=${backends[0]}
  if ! backend_is_ours "$backend" "${own[@]}"; then
    echo "tailscale serve $label left in place: it points to a foreign backend ($backend) -- run \`tailscale serve status\` to inspect it" >&2
    return 1
  fi
  if tailscale serve --https="$https" --set-path="$path" off >/dev/null 2>&1; then
    echo "removed tailscale serve $label ($backend)"
    return 0
  fi
  echo "tailscale serve $label left in place: \`tailscale serve --https=$https --set-path=$path off\` failed -- run \`tailscale serve status\` to inspect it" >&2
  return 1
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
# A16: applies the SAME %/\/" escaping install.sh's own python3 templating
# uses to embed a repo/release path inside a systemd ExecStart= line's
# quotes (see install.sh's unit-rendering step). Needed wherever a KNOWN
# path (the managed "current" symlink target, most importantly) has to be
# compared against what an EXISTING unit file's ExecStart= line actually
# says: that text is ALREADY escaped that way, so comparing it against an
# unescaped path silently never matches whenever the path contains a
# literal %, \ or " -- a real managed install on such a $HOME used to
# misdetect as channel=unknown (bin/serverjack-ctl's detect_channel()) or
# fail to recognize its own rerun (bin/serverjack-setup's
# handle_existing_install()).
systemd_escape_path() {
  python3 - "$1" <<'PY'
import sys
s = sys.argv[1]
s = s.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
print(s)
PY
}

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

# A3: ONE read-modify-write for ~/.local/share/serverjack/install.json,
# shared by the bootstrap, serverjack-ctl and serverjack-setup -- each used
# to hand-roll its own write of a FIXED set of keys, so a caller that only
# meant to change ONE field (serverjack-setup's record_install_args(), for
# install_args alone, after the rerun menu's publish option runs install.sh
# again) silently dropped every OTHER key a different writer had set that
# it didn't know about -- most importantly "state": "activating", left by
# an interrupted `serverjack-ctl update`/`rollback` (see cmd_update()'s own
# comment on why that field has to survive an interrupt to keep `status`/
# `rollback` honest). This preserves any key it isn't explicitly told to
# touch, so a caller that only cares about one field can only ever affect
# that field.
#
# Usage: update_install_json PATH  [KEY VALUE]...  (--keep-args | --set-args ARG...)
#   KEY VALUE pairs are applied in order; VALUE "__NULL__" stores JSON null,
#   VALUE "__DELETE__" removes that key entirely, anything else is stored as
#   a plain JSON string. The KEY VALUE pairs MUST be followed by exactly one
#   of:
#     --keep-args          leave "install_args" exactly as it already is
#     --set-args ARG...    replace "install_args" with these (may be none)
#   Creates the file (starting from {}) if it doesn't exist yet, or isn't
#   valid JSON. Atomic (write to a temp file, then os.replace).
update_install_json() {
  local path=$1; shift
  local -a kv=()
  local mode='' args_marker_seen=0
  local -a args=()
  while (( $# )); do
    case "$1" in
      --keep-args) mode="keep"; shift; args_marker_seen=1; break ;;
      --set-args)  mode="set"; shift; args=("$@"); args_marker_seen=1; break ;;
      *) kv+=("$1" "${2?update_install_json: KEY '$1' has no VALUE}"); shift 2 ;;
    esac
  done
  (( args_marker_seen )) \
    || { echo "update_install_json: missing --keep-args or --set-args" >&2; return 1; }
  python3 - "$path" "$mode" "${#kv[@]}" "${kv[@]}" -- "${args[@]}" <<'PY'
import json
import os
import sys

path, mode, nkv = sys.argv[1], sys.argv[2], int(sys.argv[3])
rest = sys.argv[4:]
kv = rest[:nkv]
args = rest[nkv + 1:]  # rest[nkv] is the "--" separator this function always passes

try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        doc = {}
except (OSError, ValueError):
    doc = {}

it = iter(kv)
for key in it:
    val = next(it)
    if val == "__DELETE__":
        doc.pop(key, None)
    elif val == "__NULL__":
        doc[key] = None
    else:
        doc[key] = val

if mode == "set":
    doc["install_args"] = args

directory = os.path.dirname(path) or "."
os.makedirs(directory, exist_ok=True)
tmp = path + ".tmp.%d" % os.getpid()
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PY
}
