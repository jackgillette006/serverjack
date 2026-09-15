#!/usr/bin/env bash
# Headless-browser tests, entirely in containers (needs docker; nothing else
# has to be running -- the harness starts its own serverjack and ttyd).
#   bash tests/run.sh                 # all suites; plus managed-install.sh and
#                                      # guided-install.sh when
#                                      # SERVERJACK_TEST_MANAGED=1, or when this
#                                      # is not a CI run (CI skips both by
#                                      # default -- see below)
#   bash tests/run.sh pwclip          # one Playwright suite only (fast)
#   bash tests/run.sh managed-install # ONLY the release/bootstrap/serverjack-ctl
#                                      # container test (see managed-install.sh) --
#                                      # skips the rest of this harness (and the
#                                      # Playwright container) entirely; needs
#                                      # docker able to run --privileged
#                                      # containers with real systemd, and skips
#                                      # itself with a message otherwise
#   bash tests/run.sh guided-install  # just the serverjack-setup (prerequisites/
#                                      # Tailscale/allow-list/shared-machine)
#                                      # container test (see guided-install.sh);
#                                      # same docker requirement, same skip behavior
#
# There is one listener per instance now: serverjack serves the terminal itself
# by proxying /term/ to ttyd's Unix socket, so the browsers talk straight to
# serverjack and no nginx is involved. It starts, in tcp mode:
# The harness chooses three unused loopback ports for the ordinary, restricted,
# and autostart instances. Each gets its own scratch XDG_RUNTIME_DIR, and every
# process uses a per-run tmux server. Nothing connects to the user's tmux socket
# or runtime directory.
#
# Then a scratch tmux session "pwtest", and Chromium / Firefox / WebKit (iPhone
# 14 emulation) driven with Playwright, reading the tmux pane from the host
# socket to prove keystrokes really arrived. Screenshots land in tests/shots/.
# Emulated WebKit is NOT iOS Safari.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
export PATH="$HOME/.local/bin:$PATH"
mkdir -p shots

# `bash tests/run.sh managed-install` (or `guided-install`) on its own means
# ONLY that container test -- skip the whole host-side harness below (unit
# tests, three serverjack/ttyd instances, security/host/peer-uid checks,
# autostart) and the Playwright container entirely, rather than paying for
# all of that to run one unrelated test. (Naming one alongside other suites,
# e.g. `pwclip managed-install`, is a different, deliberate multi-target
# invocation and keeps running everything asked for -- see the dispatch
# logic further down.)
if [[ $# -eq 1 && $1 == managed-install ]]; then
  bash ./managed-install.sh 2>&1 | tee shots/managed-install.log
  exit "${PIPESTATUS[0]}"
fi
if [[ $# -eq 1 && $1 == guided-install ]]; then
  bash ./guided-install.sh 2>&1 | tee shots/guided-install.log
  exit "${PIPESTATUS[0]}"
fi

# tmux prefers $TMUX from an enclosing session over TMUX_TMPDIR. Drop it and
# give the harness a private socket tree. The explicit path is also mounted
# into the browser container so its assertions inspect only this tmux server.
TEST_TMP_BASE=${TMPDIR:-/tmp}
TEST_TMP_BASE=${TEST_TMP_BASE%/}
RUN_ROOT=$(mktemp -d "$TEST_TMP_BASE/serverjack-tests.XXXXXX")
chmod 700 "$RUN_ROOT"
unset TMUX
export TMUX_TMPDIR="$RUN_ROOT/tmux"
mkdir -m 700 "$TMUX_TMPDIR"
TMUX_SOCK="$TMUX_TMPDIR/tmux-$(id -u)/default"

# One scratch runtime dir per instance: ttyd.sock lives in it, and two ttyds
# cannot share one. 0700, exactly as serverjack insists on.
RT=$RUN_ROOT/rt
RT_AUTH=$RUN_ROOT/rt-auth
RT_AUTO=$RUN_ROOT/rt-auto
RT_THEME=$RUN_ROOT/rt-theme
for d in "$RT" "$RT_AUTH" "$RT_AUTO" "$RT_THEME"; do mkdir -m 700 "$d"; done
pids=()
BROWSER_CID=$RUN_ROOT/browser.cid
cleanup() {
  if [[ -s $BROWSER_CID ]]; then
    IFS= read -r container_id < "$BROWSER_CID" || true
    if [[ ${container_id:-} =~ ^[0-9a-f]{12,64}$ ]]; then
      docker rm -f "$container_id" >/dev/null 2>&1 || true
    fi
  fi
  for p in "${pids[@]:-}"; do [[ -n $p ]] && kill "$p" 2>/dev/null || true; done
  for p in "${pids[@]:-}"; do [[ -n $p ]] && wait "$p" 2>/dev/null || true; done
  tmux -S "$TMUX_SOCK" kill-server 2>/dev/null || true
  case $RUN_ROOT in
    "$TEST_TMP_BASE"/serverjack-tests.*) rm -rf -- "$RUN_ROOT" ;;
  esac
}
trap cleanup EXIT

# Dynamic ports avoid interacting with an existing serverjack or concurrent
# test run. Keep all four sockets open while selecting so they are distinct.
read -r PORT PORT_AUTH PORT_AUTO PORT_THEME < <(python3 - <<'PY'
import socket

sockets = []
for _ in range(4):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sockets.append(sock)
print(*(sock.getsockname()[1] for sock in sockets))
PY
)
BASE="http://127.0.0.1:$PORT"
AUTH_BASE="http://127.0.0.1:$PORT_AUTH"
THEME_BASE="http://127.0.0.1:$PORT_THEME"
failures=0
result() {
  local label=$1 expected=$2 got=$3
  if [[ $got == "$expected" ]]; then
    echo "  PASS $label"
  else
    echo "  FAIL $label  -- got $got, wanted $expected"
    failures=$((failures + 1))
  fi
}
echo "== ttyd wrapper security (host-side)"
bash ./security-wrapper.sh

# Plain unittest against bin/serverjack's pure(ish) helpers -- no server, no
# browser, imports the file with importlib since it has no .py suffix. Runs
# before anything else starts so a broken helper fails fast.
echo "== unit tests (host-side)"
python3 ./test_unit.py

# B3: the physical launcher (bootstrap/launcher.sh) served from
# jackgillette.com/serverjack/install.sh. No Docker needed (curl, python3
# for a local fixture server, and `script` for a real pty) -- runs
# host-side, same as the two suites just above.
echo "== launcher (host-side)"
bash ./launcher.sh

# B4: serverjack-ctl's units_active() (OR vs AND) and the health-check
# curls' per-request timeout. No Docker needed (a fake systemctl, and a
# real python3 socket that accepts and never responds) -- host-side.
echo "== ctl health checks (host-side)"
bash ./ctl-health.sh

# A throwaway HOME, created before anything below reads it: bin/serverjack's
# channel detection (_install_channel()) resolves ~/.local/share/serverjack
# off the REAL HOME unless told otherwise, so on a machine that has (or ever
# gets) a real managed install for this account, these test instances would
# read ITS install.json/current -- unrelated to, and possibly misclassifying,
# the checkout under test. Every serverjack/serverjack-ttyd instance below
# gets this HOME, not just the tmux login shells that already needed one.
TEST_HOME=$RUN_ROOT/home
mkdir -m 700 "$TEST_HOME"
printf '%s\n' "PS1='serverjack-test\$ '" > "$TEST_HOME/bashrc"
printf -v session_shell 'exec env HOME=%q bash --noprofile --rcfile %q -i' \
  "$TEST_HOME" "$TEST_HOME/bashrc"

# A throwaway config dir with two fake agents, so the agent-card tests are
# deterministic and never touch a real coding CLI or the user's shortcuts.
CFG=$RUN_ROOT/cfg
mkdir -m 700 "$CFG"

# A directory that is NOT on PATH, standing in for a coding CLI's private
# install dir (nvm's versioned bin, ~/.local/bin) that only tools.json's
# "paths" globs know about. Regression test for the bug where a tool only
# reachable via TOOL_PATH showed as installed but failed to start with
# "command not found", because bash -lc's login shell resets PATH before
# running the command -- see command_args() in bin/serverjack.
TOOLPATH_DIR=$RUN_ROOT/toolpath
mkdir -m 700 "$TOOLPATH_DIR"
cat > "$TOOLPATH_DIR/pathfake" <<'SH'
#!/bin/sh
echo TOOL_RAN
SH
chmod +x "$TOOLPATH_DIR/pathfake"

cat > "$CFG/tools.json" <<JSON
[{"id": "fake", "label": "Fake tool", "bin": "true", "login": "echo LOGIN_RAN",
  "login_check": "true", "run": "bash",
  "actions": [{"label": "hello", "cmd": "echo ACTION_RAN"}]},
 {"id": "fake2", "label": "Fake two", "bin": "true", "run": "bash"},
 {"id": "pathfake", "label": "Path fixture", "bin": "pathfake", "run": "pathfake",
  "paths": ["$TOOLPATH_DIR"]}]
JSON
# SERVERJACK_TRUST_UIDS=101 is not needed to reach anything here any more (no
# proxy in front), but the peer-uid check below still proves it works.
# SERVERJACK_TERM_THEME= and TTYD_EXTRA_ARGS= pin those two to empty rather
# than whatever a maintainer's own shell happens to have set (both have been
# found already set in a real terminal session here) -- otherwise an
# opted-out or customized ambient environment could make the suite fail for
# a reason that has nothing to do with the change under test.
# shellcheck disable=SC2054  # the comma is inside SERVERJACK_TOOLS's value, not an array separator
common=(HOME="$TEST_HOME" SERVERJACK_LISTEN=tcp SERVERJACK_TITLE=test SERVERJACK_CONFIG="$CFG"
        SERVERJACK_TOOLS=fake,fake2,pathfake SERVERJACK_TRUST_UIDS=101
        SERVERJACK_TERM_THEME= TTYD_EXTRA_ARGS=)
env "${common[@]}" XDG_RUNTIME_DIR="$RT" SERVERJACK_PORT="$PORT" \
    python3 ../bin/serverjack >shots/web.log 2>&1 & pids+=($!)
env "${common[@]}" XDG_RUNTIME_DIR="$RT" \
    bash ../bin/serverjack-ttyd >shots/ttyd.log 2>&1 & pids+=($!)
# Second instance: same code, restricted to one tailnet login, own runtime dir.
# screenReaderMode puts xterm's text in the DOM (it renders to a canvas
# otherwise), which is how pwauth reads messages off the terminal. It also
# proves TTYD_EXTRA_ARGS still reaches ttyd through the wrapper.
env "${common[@]}" XDG_RUNTIME_DIR="$RT_AUTH" SERVERJACK_ALLOW=alice@example.com \
    SERVERJACK_PORT="$PORT_AUTH" python3 ../bin/serverjack >shots/web-auth.log 2>&1 & pids+=($!)
env "${common[@]}" XDG_RUNTIME_DIR="$RT_AUTH" SERVERJACK_ALLOW=alice@example.com \
    TTYD_EXTRA_ARGS='-t screenReaderMode=true' \
    bash ../bin/serverjack-ttyd >shots/ttyd-auth.log 2>&1 & pids+=($!)
# Third instance: a user's own -t theme=... in TTYD_EXTRA_ARGS must be what
# actually applies, not bin/serverjack's generated one on top of it --
# pwtest.py's "custom TTYD_EXTRA_ARGS theme" check loads this instance and
# reads the rendered background back. Own runtime dir (a ttyd.sock can't be
# shared), but the same tmux server as the first instance (TMUX_TMPDIR is
# inherited from the environment this whole script runs in, not overridden
# here), so the already-seeded "pwtest" session works for it too.
#
# The \" pairs are load-bearing, not decoration: bin/serverjack-ttyd parses
# TTYD_EXTRA_ARGS with shlex.split(posix=True), which treats a bare "..."
# as shell-style quoting and *strips* the quote characters -- a plain
# theme={"background":"#123456"} would arrive at ttyd (and its JSON.parse)
# as theme={background:#123456}, invalid JSON. Backslash-escaping the inner
# quotes is what makes shlex preserve them literally.
env "${common[@]}" XDG_RUNTIME_DIR="$RT_THEME" SERVERJACK_PORT="$PORT_THEME" \
    TTYD_EXTRA_ARGS='-t theme={\"background\":\"#123456\"}' \
    python3 ../bin/serverjack >shots/web-theme.log 2>&1 & pids+=($!)
env "${common[@]}" XDG_RUNTIME_DIR="$RT_THEME" \
    TTYD_EXTRA_ARGS='-t theme={\"background\":\"#123456\"}' \
    bash ../bin/serverjack-ttyd >shots/ttyd-theme.log 2>&1 & pids+=($!)
tmux new-session -d -s pwtest -x 120 -y 30 -c "$TEST_HOME" "$session_shell"
tmux new-session -d -s pwother -x 120 -y 30 -c "$TEST_HOME" "$session_shell"
for _ in $(seq 1 30); do curl -sf -o /dev/null "$BASE/" && break; sleep 0.2; done
curl -sf -o /dev/null "$BASE/" || { echo "landing not up (see shots/web.log)" >&2; exit 1; }
curl -sf -o /dev/null "$BASE/term/" || { echo "terminal not reachable through serverjack (see shots/ttyd.log)" >&2; exit 1; }
curl -sf -o /dev/null "$AUTH_BASE/healthz" || { echo "restricted instance not up (see shots/web-auth.log)" >&2; exit 1; }
curl -sf -o /dev/null "$THEME_BASE/healthz" || { echo "custom-theme instance not up (see shots/web-theme.log)" >&2; exit 1; }

echo "== HTTP parser and identity security (host-side)"
SERVERJACK_TEST_BASE="$BASE" SERVERJACK_TEST_AUTH_BASE="$AUTH_BASE" \
  python3 ./security_http.py

# Host validation: a name we don't answer to must not reach any route, so a
# rebinding attack can't drive this from a browser it tricked.
echo "== Host validation (host-side)"
hostcode() { curl -s -o /dev/null -w '%{http_code}' -H "Host: $1" "$BASE$2" || echo 000; }
# (no `set --` here: it would clobber $@, which still holds the suite names)
for probe_path in / /healthz /term/; do
  got=$(hostcode evil.example "$probe_path")
  result "Host: evil.example $probe_path" 421 "$got"
done
got=$(hostcode "localhost:$PORT" /healthz)
result "Host: localhost:$PORT /healthz" 200 "$got"

# Peer-uid check, from the host: another local account must be refused, we must
# not be. Playwright can't help -- its container runs as root, which is allowed
# on purpose (that is how tailscaled reaches us).
echo "== peer-uid (host-side)"
uidcheck() {   # $1 label, $2 path, $3 expected code, $4.. docker user flags
  local got
  got=$(docker run --rm --network host "${@:4}" "$IMG" \
          curl -s -o /dev/null -w '%{http_code}' "$BASE$2" 2>/dev/null | tail -1)
  result "$1" "$3" "$got"
}
own=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")
result "the owning account gets in" 200 "$own"
uidcheck "another local user (uid 65534) is refused" / 403 --user 65534
uidcheck "...and cannot reach the terminal either" /term/ 403 --user 65534
uidcheck "root (tailscaled's uid) gets in" / 200 --user 0
uidcheck "the trusted proxy uid (101) gets in" / 200 --user 101

# The terminal's WebSocket, through serverjack's proxy: same origin accepted,
# foreign origin refused by ttyd -O (which still sees the real Host/Origin
# because the proxy forwards them verbatim).
echo "== terminal websocket (host-side)"
if python3 ../bin/ttyd-ws-check.py "$BASE/term/"; then
  echo "  PASS same-origin 101, foreign origin refused"
else
  echo "  FAIL websocket origin behaviour through the proxy"
  failures=$((failures + 1))
fi

# ---------------------------------------------------------------- autostart
# autostart.json is a boot-time thing, so it gets its own throwaway instance
# rather than a browser: a config dir with one fake tool whose "server" is
# `sleep 300`, an autostart entry for it, and a 2-second delay instead of 15.
# Passing means the tmux session appeared without anyone pressing a button.
echo "== autostart (host-side)"
ACFG=$RUN_ROOT/cfg-auto
mkdir -m 700 "$ACFG"
cat > "$ACFG/tools.json" <<'JSON'
[{"id": "fakesrv", "label": "Fake server", "bin": "true", "run": "bash",
  "server": {"label": "Fake server", "cmd": "sleep 300", "session": "pwauto"}}]
JSON
cat > "$ACFG/autostart.json" <<'JSON'
[{"tool": "fakesrv", "kind": "server", "dir": "."}]
JSON
auto=(HOME="$TEST_HOME" SERVERJACK_LISTEN=tcp SERVERJACK_TITLE=test XDG_RUNTIME_DIR="$RT_AUTO" SERVERJACK_CONFIG="$ACFG"
      SERVERJACK_TOOLS=fakesrv SERVERJACK_PORT="$PORT_AUTO" SERVERJACK_AUTOSTART_DELAY=2)
env "${auto[@]}" python3 ../bin/serverjack >shots/web-auto.log 2>&1 & pids+=($!)
for _ in $(seq 1 30); do tmux has-session -t =pwauto 2>/dev/null && break; sleep 0.5; done
if tmux has-session -t =pwauto 2>/dev/null; then
  echo "  PASS autostart started the fake server's session"
  if grep -q 'autostart: started fakesrv server' shots/web-auto.log; then
    echo "  PASS ...and said so on stderr"
  else
    echo "  FAIL ...and said so on stderr  -- $(tail -1 shots/web-auto.log)"
    failures=$((failures + 1))
  fi
else
  echo "  FAIL autostart started the fake server's session  -- $(tail -3 shots/web-auto.log | tr '\n' ' ')"
  failures=$((failures + 1))
fi
tmux kill-session -t =pwauto 2>/dev/null

# "managed-install" and "guided-install" are not Playwright suites (no
# matching .py file) -- each selects one of the separate, heavier container
# tests below instead. No args means the full default suite list, PLUS both
# container tests -- but only when they're likely to actually work and not
# just eat minutes: SERVERJACK_TEST_MANAGED=1 forces both, and otherwise
# each runs unless this looks like a CI run (both need --privileged
# docker-in-docker with real systemd, which CI runners can't reliably
# provide, so they used to run -- and often fail for reasons unrelated to
# the code under test -- on every CI run by default). Explicit suite names
# (e.g. `pwclip`) mean just those, for fast iteration, unless one of the two
# is named among them too (which always runs it, regardless of
# SERVERJACK_TEST_MANAGED/CI -- naming it is opting in).
run_managed=0
run_guided=0
explicit_args=("$@")
if (( ${#explicit_args[@]} == 0 )); then
  if [[ ${SERVERJACK_TEST_MANAGED:-0} == 1 ]]; then
    run_managed=1
    run_guided=1
  elif [[ -z ${CI:-} ]]; then
    run_managed=1
    run_guided=1
  else
    echo "skipping managed-install.sh and guided-install.sh on CI by default" >&2
    echo "(both need --privileged docker with real systemd, which CI runners" >&2
    echo "can't reliably provide); set SERVERJACK_TEST_MANAGED=1 to force them," >&2
    echo "or run either on its own:" >&2
    echo "  bash tests/run.sh managed-install" >&2
    echo "  bash tests/run.sh guided-install" >&2
  fi
fi
suites=()
for a in "${explicit_args[@]}"; do
  case "$a" in
    managed-install) run_managed=1 ;;
    guided-install)  run_guided=1 ;;
    *) suites+=("$a") ;;
  esac
done
[[ ${#suites[@]} -eq 0 && ${#explicit_args[@]} -eq 0 ]] \
  && suites=(pwtest pwclip pwmobile pwpop pwland pwauth pwwin)
for suite in "${suites[@]}"; do
  [[ $suite =~ ^[a-zA-Z0-9_-]+$ && -f $suite.py ]] \
    || { echo "unknown test suite: $suite" >&2; exit 2; }
done
set +e
browser_status=0
if (( ${#suites[@]} )); then
  docker run --rm --cidfile "$BROWSER_CID" --network host \
    -v "$PWD:/w" -w /w -v "$RUN_ROOT:$RUN_ROOT" -v "$PWD/../bin:/repo-bin:ro" \
    -e TMUX_SOCK="$TMUX_SOCK" -e SERVERJACK_TEST_BASE="$BASE" \
    -e SERVERJACK_TEST_AUTH_BASE="$AUTH_BASE" -e SERVERJACK_TEST_THEME_BASE="$THEME_BASE" \
    "$IMG" bash -c '
    set -euo pipefail
    # Pillow: pwtest.py decodes a screenshot clip to prove a terminal glyph is
    # visible against its cursor cell (more than one color in it).
    pip install -q --timeout 15 --retries 1 playwright==1.62.0 Pillow >/dev/null 2>&1
    (apt-get -qq update && apt-get -qq install -y tmux) >/dev/null 2>&1
    failed=0
    for s in "$@"; do
      echo "== $s"
      if ! python3 "$s.py"; then failed=1; fi
    done
    exit "$failed"' browser-tests "${suites[@]}" 2>&1 \
    | grep -v 'GL Driver\|maybe unknown option' | tee shots/browser.log
  browser_status=${PIPESTATUS[0]}
fi

# Optional, host-side, needs docker able to run --privileged containers with
# real systemd -- each script itself detects that and skips (exit 0) with a
# clear message when it can't, rather than failing the whole suite.
managed_status=0
if (( run_managed )); then
  echo "== managed-install (host-side)"
  bash ./managed-install.sh 2>&1 | tee shots/managed-install.log
  managed_status=${PIPESTATUS[0]}
fi
guided_status=0
if (( run_guided )); then
  echo "== guided-install (host-side)"
  bash ./guided-install.sh 2>&1 | tee shots/guided-install.log
  guided_status=${PIPESTATUS[0]}
fi
set -e
if (( failures > 0 )); then
  echo "$failures host-side check(s) failed" >&2
fi
(( browser_status == 0 && managed_status == 0 && guided_status == 0 && failures == 0 ))
