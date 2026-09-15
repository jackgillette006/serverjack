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
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)

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
  rm -rf "$WORK"
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

echo
if (( failures > 0 )); then
  echo "$failures ctl-health check(s) failed" >&2
fi
exit $(( failures > 0 ))
