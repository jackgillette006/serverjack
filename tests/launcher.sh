#!/usr/bin/env bash
# Tests bootstrap/launcher.sh (B3) -- the thin launcher meant to be served
# as a physical file from https://jackgillette.com/serverjack/install.sh.
# No Docker and no systemd needed: only curl, python3 (a local fixture HTTP
# server standing in for the real GitHub release asset, via
# SERVERJACK_TEST_RELEASE_URL) and `script` (a real pty, for the two
# terminal-detection cases -- downloaded-then-run vs. piped). Wired into
# `bash tests/run.sh` alongside the other suites (not gated behind Docker
# the way managed-install.sh/guided-install.sh are).
#
# What this proves, against the REAL bootstrap/launcher.sh, never a mock:
#   - downloaded-then-run (stdin is a real terminal)
#   - curl|bash-style piped use (stdin is not a terminal, but a controlling
#     terminal -- /dev/tty -- is still available for the bootstrap's own
#     prompts)
#   - no controlling terminal at all: a clean, actionable failure, nothing
#     left behind
#   - a truncated download (missing the bootstrap template's own
#     end-of-file marker) is refused, not run partially
#   - an HTML response (wrong URL, a hosting error page) is refused by its
#     first line, not run as a script
#   - an empty response is refused
#   - a failed download (404) is refused with a clear message
#   - arguments and the bootstrap's own exit status are forwarded exactly
#   - the downloaded temp file is removed whether the run succeeds or fails
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)
LAUNCHER="$REPO/bootstrap/launcher.sh"
[[ -f $LAUNCHER ]] || { echo "missing $LAUNCHER" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "python3 not found -- skipping tests/launcher.sh" >&2; exit 0; }
command -v script >/dev/null 2>&1 || { echo "script not found -- skipping tests/launcher.sh" >&2; exit 0; }

failures=0
result() {  # $1 label  $2 expected  $3 got
  if [[ $3 == "$2" ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1 -- got $3, wanted $2"
    failures=$((failures + 1))
  fi
}
contains() {  # $1 label  $2 haystack  $3 needle
  if [[ $2 == *"$3"* ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1 -- expected to find: $3"
    echo "$2" | sed 's/^/    | /'
    failures=$((failures + 1))
  fi
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-launcher-test.XXXXXX")
SRV_PID=""
cleanup() {
  [[ -n $SRV_PID ]] && kill "$SRV_PID" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# ------------------------------------------------------------- fixtures
mkdir -p "$WORK/webroot/good" "$WORK/webroot/truncated" "$WORK/webroot/html" "$WORK/webroot/empty"

EOF_MARKER='# SERVERJACK-BOOTSTRAP-EOF -- do not remove: bootstrap/launcher.sh (and the'
good="$WORK/webroot/good/serverjack-bootstrap.sh"
cat > "$good" <<EOF
#!/usr/bin/env bash
echo "LAUNCHER_TEST_ARGS:\$*"
echo "LAUNCHER_TEST_TTY:\$([ -t 0 ] && echo yes || echo no)"
exit 42
$EOF_MARKER
EOF

# Truncated: a real cut-off transfer -- same start, no end-of-file marker.
head -n3 "$good" > "$WORK/webroot/truncated/serverjack-bootstrap.sh"

# An HTML error page instead of the script (wrong URL, or a hosting hiccup
# that answers 200 with its own error page).
cat > "$WORK/webroot/html/serverjack-bootstrap.sh" <<'EOF'
<html><body><h1>404 Not Found</h1></body></html>
EOF

: > "$WORK/webroot/empty/serverjack-bootstrap.sh"

# ------------------------------------------------------- local fixture server
PORT=$(( 20000 + ($$ % 10000) ))
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$WORK/webroot" \
  >"$WORK/httpd.log" 2>&1 &
SRV_PID=$!
ok=0
for _ in $(seq 1 50); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/good/serverjack-bootstrap.sh" 2>/dev/null && { ok=1; break; }
  sleep 0.1
done
(( ok )) || { echo "fixture HTTP server never came up:" >&2; cat "$WORK/httpd.log" >&2; exit 1; }

# Runs the REAL launcher against fixture $1 (a webroot subdir), with a
# private TMPDIR so temp-file-cleanup can be checked afterward. $2.. are
# extra args to launcher.sh itself. Prints stdout+stderr; sets RC.
run_launcher() {
  local sub=$1; shift
  rm -rf "$WORK/tmpdir"; mkdir -p "$WORK/tmpdir"
  set +e
  OUT=$(TMPDIR="$WORK/tmpdir" \
        SERVERJACK_TEST_RELEASE_URL="http://127.0.0.1:$PORT/$sub/serverjack-bootstrap.sh" \
        bash "$LAUNCHER" "$@" 2>&1)
  RC=$?
  set -e
}

leftover_tmp() { find "$WORK/tmpdir" -mindepth 1 2>/dev/null | wc -l | tr -d ' '; }

echo "================================================================"
echo "(a) downloaded-then-run: stdin is a real terminal"
rm -rf "$WORK/tmpdir"; mkdir -p "$WORK/tmpdir"
script -qfc "TMPDIR='$WORK/tmpdir' SERVERJACK_TEST_RELEASE_URL='http://127.0.0.1:$PORT/good/serverjack-bootstrap.sh' bash '$LAUNCHER' --no-serve --port 7777 > '$WORK/out-a.txt' 2>&1; echo EXIT:\$? >> '$WORK/out-a.txt'" /dev/null >/dev/null
out=$(cat "$WORK/out-a.txt")
contains "(a) args forwarded" "$out" "LAUNCHER_TEST_ARGS:--no-serve --port 7777"
contains "(a) ran with a real tty (downloaded-then-run)" "$out" "LAUNCHER_TEST_TTY:yes"
contains "(a) exit status forwarded (42)" "$out" "EXIT:42"
result "(a) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(b) curl|bash-style piped use: stdin not a tty, /dev/tty still available"
rm -rf "$WORK/tmpdir"; mkdir -p "$WORK/tmpdir"
script -qfc "TMPDIR='$WORK/tmpdir' SERVERJACK_TEST_RELEASE_URL='http://127.0.0.1:$PORT/good/serverjack-bootstrap.sh' bash '$LAUNCHER' --unix > '$WORK/out-b.txt' 2>&1 </dev/null; echo EXIT:\$? >> '$WORK/out-b.txt'" /dev/null >/dev/null
out=$(cat "$WORK/out-b.txt")
contains "(b) args forwarded" "$out" "LAUNCHER_TEST_ARGS:--unix"
contains "(b) ran with stdin redirected from /dev/tty (piped use)" "$out" "LAUNCHER_TEST_TTY:yes"
contains "(b) exit status forwarded (42)" "$out" "EXIT:42"
result "(b) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(c) no controlling terminal at all: clean failure, nothing left behind"
rm -rf "$WORK/tmpdir"; mkdir -p "$WORK/tmpdir"
set +e
out=$(setsid bash -c "TMPDIR='$WORK/tmpdir' SERVERJACK_TEST_RELEASE_URL='http://127.0.0.1:$PORT/good/serverjack-bootstrap.sh' bash '$LAUNCHER'" </dev/null 2>&1 </dev/null)
rc=$?
set -e
result "(c) exits non-zero" "1" "$rc"
contains "(c) explains there is no controlling terminal" "$out" "no controlling terminal"
result "(c) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(d) a truncated download (missing end-of-file marker) is refused"
run_launcher truncated
result "(d) exits non-zero" "1" "$RC"
contains "(d) refuses a truncated file" "$OUT" "looks truncated"
result "(d) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(e) an HTML response is refused, not run"
run_launcher html
result "(e) exits non-zero" "1" "$RC"
contains "(e) refuses a non-script response" "$OUT" "does not look like the bootstrap"
result "(e) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(f) an empty response is refused"
run_launcher empty
result "(f) exits non-zero" "1" "$RC"
contains "(f) refuses an empty download" "$OUT" "is empty"
result "(f) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(g) a failed download (404) is refused with a clear message"
run_launcher missing-path-does-not-exist
result "(g) exits non-zero" "1" "$RC"
contains "(g) reports the download failure" "$OUT" "download failed"
result "(g) temp files cleaned up" "0" "$(leftover_tmp)"

echo "================================================================"
echo "(h) C1: the prerequisite floor is checked before anything is fetched"
# A restricted PATH standing in for a machine missing python3 -- symlink
# only the OTHER floor binaries plus apt-get (so the sudo-command branch is
# exercised), never python3 itself. No /dev/tty here either (this is a
# plain, non-piped `bash` subshell, no `script` wrapper), so this also
# proves the no-terminal path: print the command, exit 2, never hang.
FAKEPATH="$WORK/fakepath"
mkdir -p "$FAKEPATH"
for b in bash curl tar sha256sum systemctl flock apt-get dpkg id; do
  real=$(command -v "$b" 2>/dev/null) || continue
  ln -sf "$real" "$FAKEPATH/$b"
done
set +e
out=$(env -i PATH="$FAKEPATH" HOME="$WORK" \
      SERVERJACK_TEST_RELEASE_URL="http://127.0.0.1:$PORT/good/serverjack-bootstrap.sh" \
      bash "$LAUNCHER" </dev/null 2>&1)
rc=$?
set -e
result "(h) exits 2 (not 0 or 1)" "2" "$rc"
contains "(h) names the missing prerequisite" "$out" "python3"
contains "(h) shows the apt-get install command" "$out" "sudo apt-get install"
[[ $out != *"Fetching bootstrap from"* ]] && echo "  PASS (h) never even tried to download anything" \
  || { echo "  FAIL (h) tried to download despite the missing prerequisite -- got: $out"; failures=$((failures + 1)); }

echo
if (( failures > 0 )); then
  echo "$failures launcher check(s) failed" >&2
fi
exit $(( failures > 0 ))
