#!/usr/bin/env bash
# Host-side (no Docker, no real systemd needed) regression tests for B4:
#   1. `systemctl is-active PATTERN...` with MULTIPLE unit names is a
#      logical OR (systemctl(1): "exit code 0 if AT LEAST ONE is active"),
#      not AND -- bin/serverjack-ctl's units_active() used to be a single
#      such call, so it reported healthy with only one of the two units up.
#      A fake systemctl on PATH drives every combination directly against
#      the REAL units_active() (bin/serverjack-ctl is sourced, not
#      reimplemented -- see the guard at its own end).
#   2. The local health-check curls (bin/serverjack-lib.sh's
#      local_http_code()/wait_local_healthz()) used to have no per-request
#      timeout, so a listener that ACCEPTS a connection and then never
#      responds (not the same as connection-refused, which curl reports
#      immediately) could hang a single request forever -- a real Python
#      socket server does exactly that here, against the real curl binary.
# And for B5:
#   3. backup_current_state()/restore_from_backup() now also snapshot and
#      restore ~/.local/bin/ttyd and fzf, which install.sh replaces
#      whenever a release bumps either pin -- proven directly against the
#      real functions (bin/serverjack-ctl sourced, HOME pointed at a
#      private sandbox for the whole file so nothing here can ever touch a
#      real account's actual serverjack install).
# And for A3:
#   4. bin/serverjack-lib.sh's update_install_json() -- the shared install.json
#      read-modify-write -- actually preserves keys it isn't told to touch
#      (most importantly "state"), proven directly against the real function.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)

# Every section below shares one private HOME -- backup_current_state()/
# restore_from_backup() (section c) read/write real paths under it
# (~/.local/share/serverjack, ~/.local/bin/*), so this must never be the
# real invoking account's actual HOME.
export HOME
HOME=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-ctl-health-home.XXXXXX")

failures=0
result() {  # $1 label  $2 expected  $3 got
  if [[ $3 == "$2" ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1 -- got $3, wanted $2"
    failures=$((failures + 1))
  fi
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-ctl-health-test.XXXXXX")
HANG_PID=""
cleanup() {
  [[ -n $HANG_PID ]] && kill "$HANG_PID" >/dev/null 2>&1 || true
  rm -rf "$WORK" "$HOME"
}
trap cleanup EXIT

echo "================================================================"
echo "(a) units_active() genuinely requires BOTH units (B4 -- OR vs AND)"

# A fake `systemctl` standing in for the real one: only understands
# `--user is-active --quiet serverjack` / `... serverjack-ttyd`, reading
# which units are "active" from $WORK/active-units (one name per line).
# Deliberately does NOT accept both unit names in one call -- if
# units_active() ever regresses back to a single multi-name call, this fake
# fails loudly (unknown arguments) rather than silently doing the wrong
# thing, which a fake that also implemented the (buggy) OR semantics would.
mkdir -p "$WORK/fakebin"
cat > "$WORK/fakebin/systemctl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1 $2 $3" == "--user is-active --quiet" && $# -eq 4 ]]; then
  unit=$4
  active_file="${SERVERJACK_TEST_ACTIVE_UNITS_FILE:?}"
  grep -qxF "$unit" "$active_file" 2>/dev/null
  exit $?
fi
# restore_from_backup() (section c, B5) also calls these two -- no-op
# success, since section (c) only cares about file restoration, not a real
# unit lifecycle (that's what tests/managed-install.sh exercises for real).
if [[ "$1 $2" == "--user daemon-reload" && $# -eq 2 ]]; then exit 0; fi
if [[ "$1 $2" == "--user restart" && $# -ge 3 ]]; then exit 0; fi
echo "fake systemctl: unexpected invocation: $*" >&2
exit 99
SH
chmod 755 "$WORK/fakebin/systemctl"

export SERVERJACK_TEST_ACTIVE_UNITS_FILE="$WORK/active-units"
export XDG_RUNTIME_DIR="$WORK/xdgrt"
mkdir -p "$XDG_RUNTIME_DIR"

# Source the real bin/serverjack-ctl (guarded at its own end so this does
# not also run its subcommand dispatcher) with the fake systemctl put first
# on PATH.
PATH="$WORK/fakebin:$PATH"
source "$REPO/bin/serverjack-ctl"

printf 'serverjack\nserverjack-ttyd\n' > "$WORK/active-units"
if units_active; then got=0; else got=1; fi
result "(a) both active -> healthy" "0" "$got"

printf 'serverjack\n' > "$WORK/active-units"
if units_active; then got=0; else got=1; fi
result "(a) only serverjack active (ttyd down) -> NOT healthy" "1" "$got"

printf 'serverjack-ttyd\n' > "$WORK/active-units"
if units_active; then got=0; else got=1; fi
result "(a) only serverjack-ttyd active -> NOT healthy" "1" "$got"

: > "$WORK/active-units"
if units_active; then got=0; else got=1; fi
result "(a) neither active -> NOT healthy" "1" "$got"

echo "================================================================"
echo "(b) a listener that accepts and never responds is bounded by -m, not"
echo "    left to hang the whole health-check loop"

# shellcheck source=bin/serverjack-lib.sh
source "$REPO/bin/serverjack-lib.sh"

python3 - "$WORK/hang.port" <<'PY' &
import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 0))
s.listen(5)
with open(sys.argv[1], "w") as f:
    f.write(str(s.getsockname()[1]))
while True:
    conn, _ = s.accept()
    # Accept the connection, read nothing, write nothing, close nothing --
    # the client's request just sits there.
    time.sleep(3600)
PY
HANG_PID=$!
for _ in $(seq 1 50); do [[ -s "$WORK/hang.port" ]] && break; sleep 0.1; done
HANG_PORT=$(cat "$WORK/hang.port")

start=$SECONDS
code=$(local_http_code -m 2 --connect-timeout 2 "http://127.0.0.1:$HANG_PORT/")
elapsed=$(( SECONDS - start ))
result "(b) local_http_code returns a clean 000, not a hang" "000" "$code"
if (( elapsed <= 8 )); then
  echo "  PASS (b) local_http_code bounded by -m (took ${elapsed}s)"
else
  echo "  FAIL (b) local_http_code took ${elapsed}s -- -m did not bound it"
  failures=$((failures + 1))
fi

start=$SECONDS
wait_local_healthz 3 -m 1 --connect-timeout 1 "http://127.0.0.1:$HANG_PORT/" && got=0 || got=1
elapsed=$(( SECONDS - start ))
result "(b) wait_local_healthz gives up (never sees 200)" "1" "$got"
if (( elapsed <= 8 )); then
  echo "  PASS (b) wait_local_healthz's own timeout (3s) was actually honored (took ${elapsed}s)"
else
  echo "  FAIL (b) wait_local_healthz took ${elapsed}s for a 3s budget -- a hung request blocked the loop"
  failures=$((failures + 1))
fi

echo "================================================================"
echo "(c) backup_current_state()/restore_from_backup() cover ttyd/fzf too (B5)"

mkdir -p "$HOME/.local/bin" "$HOME/.config/serverjack" "$HOME/.config/systemd/user"
printf 'GOOD_TTYD_V1\n' > "$HOME/.local/bin/ttyd"
printf 'GOOD_FZF_V1\n' > "$HOME/.local/bin/fzf"
chmod 755 "$HOME/.local/bin/ttyd" "$HOME/.local/bin/fzf"
printf 'SERVERJACK_PORT=7680\n' > "$HOME/.config/serverjack/env"
printf '[Service]\nExecStart=/bin/true\n' > "$HOME/.config/systemd/user/serverjack.service"
printf '[Service]\nExecStart=/bin/true\n' > "$HOME/.config/systemd/user/serverjack-ttyd.service"
install -m 755 "$REPO/bin/serverjack-ctl" "$HOME/.local/bin/serverjack-ctl"
install -m 755 "$REPO/bin/serverjack-setup" "$HOME/.local/bin/serverjack-setup"

backup_dir=$(backup_current_state)
[[ $(cat "$backup_dir/ttyd" 2>/dev/null) == GOOD_TTYD_V1 ]] && echo "  PASS (c) backup_current_state() snapshots ttyd" \
  || { echo "  FAIL (c) backup_current_state() did not snapshot ttyd"; failures=$((failures + 1)); }
[[ $(cat "$backup_dir/fzf" 2>/dev/null) == GOOD_FZF_V1 ]] && echo "  PASS (c) backup_current_state() snapshots fzf" \
  || { echo "  FAIL (c) backup_current_state() did not snapshot fzf"; failures=$((failures + 1)); }

# Simulate install.sh having just replaced both with a new (here: broken)
# release's copies -- the very thing that can be what caused the update to
# fail in the first place.
printf 'BROKEN_TTYD_V2\n' > "$HOME/.local/bin/ttyd"
printf 'BROKEN_FZF_V2\n' > "$HOME/.local/bin/fzf"

# Not testing wait_healthy() here (sections (a)/(b) already do, and it has
# nothing to say about file bytes) -- stub it so this doesn't also pay for
# its real 15s no-op poll against a fake systemctl/no real server.
wait_healthy() { return 0; }
mkdir -p "$HOME/.local/share/serverjack/releases/1.0.0"
restore_from_backup "1.0.0" "releases/1.0.0" "$backup_dir" >/dev/null 2>&1 || true

[[ $(cat "$HOME/.local/bin/ttyd" 2>/dev/null) == GOOD_TTYD_V1 ]] && echo "  PASS (c) restore_from_backup() restores the OLD ttyd bytes, not a new download" \
  || { echo "  FAIL (c) restore_from_backup() left ttyd as: $(cat "$HOME/.local/bin/ttyd" 2>/dev/null)"; failures=$((failures + 1)); }
[[ $(cat "$HOME/.local/bin/fzf" 2>/dev/null) == GOOD_FZF_V1 ]] && echo "  PASS (c) restore_from_backup() restores the OLD fzf bytes, not a new download" \
  || { echo "  FAIL (c) restore_from_backup() left fzf as: $(cat "$HOME/.local/bin/fzf" 2>/dev/null)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(d) update_install_json() (A3): a caller that touches one field can't"
echo "    drop any other -- most importantly \"state\""

IJSON="$WORK/install.json"
rm -f "$IJSON"
update_install_json "$IJSON" channel release version 1.0.0 installed_at 2026-01-01T00:00:00Z \
  previous __NULL__ state installing --set-args --no-serve --title box

py_get() { python3 -c "import json,sys; print(json.load(open('$IJSON')).get('$1'))"; }
result "(d) version set" "1.0.0" "$(py_get version)"
result "(d) previous is JSON null (Python None)" "None" "$(py_get previous)"
result "(d) state set" "installing" "$(py_get state)"
result "(d) install_args set" "['--no-serve', '--title', 'box']" "$(py_get install_args)"

# The A3 regression itself: a caller that ONLY passes --set-args (exactly
# what serverjack-setup's record_install_args() does) must not touch
# "state" (or version, or anything else) at all.
update_install_json "$IJSON" --set-args --unix --title box2
result "(d) --set-args-only call updates install_args" "['--unix', '--title', 'box2']" "$(py_get install_args)"
result "(d) --set-args-only call leaves state untouched" "installing" "$(py_get state)"
result "(d) --set-args-only call leaves version untouched" "1.0.0" "$(py_get version)"

# __DELETE__ actually removes the key (ctl's write_install_json uses this
# to clear "state" once an update/rollback is confirmed healthy).
update_install_json "$IJSON" state __DELETE__ --keep-args
has_state=$(python3 -c "import json; print('state' in json.load(open('$IJSON')))")
result "(d) __DELETE__ removes the key entirely" "False" "$has_state"
result "(d) --keep-args left install_args alone" "['--unix', '--title', 'box2']" "$(py_get install_args)"

# A missing/corrupt file starts from {} rather than erroring.
rm -f "$IJSON"
update_install_json "$IJSON" version 2.0.0 --keep-args
result "(d) starts fresh from a missing file" "2.0.0" "$(py_get version)"

echo
if (( failures > 0 )); then
  echo "$failures ctl-health check(s) failed" >&2
fi
exit $(( failures > 0 ))
