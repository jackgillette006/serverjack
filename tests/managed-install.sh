#!/usr/bin/env bash
# shellcheck disable=SC2088
# (the file is full of "~/..." inside double-quoted strings that are either
# passed to run_as() -- which hands them to a FRESH `bash -c` inside the
# container, where they expand normally -- or are plain human-readable
# labels for result(); neither is the local, this-shell tilde SC2088 warns
# about)
# Container test for the managed (bootstrap-installed) install path: phase B
# of serverjack-one-command-install-plan.md, steps 3 and 5. Needs docker able
# to run --privileged containers with real systemd (a "real" system manager,
# not just a shell) -- if it can't, this prints why and exits 0 (a skip, not
# a failure). Optional, host-side, wired into `bash tests/run.sh` (see there).
#
# What it proves, against a Debian 13 systemd container with NO git in the
# user's PATH and NO GitHub reachable for the serverjack release itself (a
# python3 -m http.server on a private docker network stands in, addressed via
# SERVERJACK_RELEASE_BASE_URL -- see bootstrap/serverjack-bootstrap.sh.in and
# bin/serverjack-ctl for that hook):
#
#   (a) curl-pipe-bash --no-serve installs a fresh release; /healthz is 200
#   (b) rerunning install.sh preserves the env file and a shortcut
#   (c) `serverjack-ctl update --version <bumped>` activates a second release
#       while a tmux session with a running command survives
#   (d) updating to a THIRD, deliberately broken release (its bin/serverjack
#       exits 1) is refused and auto-rolled-back; the prior version answers
#       200 again
#   (e) `serverjack-ctl update` with no --yes and no controlling terminal
#       refuses (exit 2) and changes nothing
#   (f) `serverjack-ctl rollback --yes` goes back to the very first version
#   (g) a truncated bootstrap (both the exact `head -c 2000` from the spec,
#       and a deliberately mid-function cut) executes nothing
#   (h) a corrupted archive (one byte flipped) is refused, with no release
#       ever staged
#   (i) `serverjack-ctl uninstall --yes` removes the managed install but
#       leaves ~/.config/serverjack and the tmux session running
#   (j) running the bootstrap as root is refused before anything is written
#
# ttyd and fzf are pre-fetched on the HOST (which has real internet, proven
# earlier by the setup steps) at the exact pinned versions install.sh
# expects, then served from the same private webroot -- so install.sh's own
# unrelated, pre-existing ttyd/fzf provisioning never needs GitHub either,
# and a flaky DNS blip on the test network can't produce a false failure.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)

RUNID="sjmi-$$-$(date +%s)"
IMG="serverjack-managed-install-test:latest"
NET="$RUNID-net"
FILESRV="$RUNID-filesrv"
TESTER="$RUNID-tester"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-managed-install.XXXXXX")
chmod 700 "$WORK"

failures=0
result() {  # $1 label, $2 expected, $3 got
  if [[ $3 == "$2" ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1  -- got $3, wanted $2"
    failures=$((failures + 1))
  fi
}
cleanup() {
  docker rm -f "$TESTER" "$FILESRV" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# ------------------------------------------------------------- capability
if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found -- skipping the managed-install container test" >&2
  exit 0
fi
if ! docker run --rm --privileged -e container=docker debian:13-slim true >/dev/null 2>&1; then
  echo "docker cannot run --privileged containers here -- skipping the managed-install container test" >&2
  exit 0
fi

# ------------------------------------------------------------- test image
# Deliberately no git: proves the bootstrap and serverjack-ctl need none.
# dbus-user-session + libpam-systemd are what let `systemctl --user` work at
# all for a lingered, non-logged-in account inside a container -- without
# libpam-systemd, user@<uid>.service fails outright ("$XDG_RUNTIME_DIR is not
# set", found the hard way building this test).
say() { printf '\033[1m%s\033[0m\n' "$*"; }
say "Building the test image"
cat > "$WORK/Dockerfile" <<'EOF'
FROM debian:13-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus dbus-user-session libpam-systemd \
      tmux curl ca-certificates python3 \
      iproute2 procps util-linux hostname less \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
EOF
docker build -t "$IMG" -f "$WORK/Dockerfile" "$WORK" >/tmp/"$RUNID"-build.log 2>&1 \
  || { echo "image build failed:" >&2; cat /tmp/"$RUNID"-build.log >&2; exit 1; }
rm -f /tmp/"$RUNID"-build.log

# --------------------------------------------------------- release builds
# V1 = this worktree's real, unmodified VERSION. V2 = a bumped-VERSION-only
# copy (a normal upgrade). V3 = bumped further AND broken (bin/serverjack
# exits 1 immediately) -- proves auto-rollback. V4 = another good bump whose
# SERVED archive gets one byte flipped after building -- its bootstrap still
# carries the correct pinned sha256, so the mismatch is what must be caught.
V1=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$REPO/bin/serverjack")
V2="9.9.9-test"
V3="9.9.10-broken-test"
V4="9.9.6-corrupt-test"
[[ -n $V1 ]] || { echo "could not read VERSION from bin/serverjack" >&2; exit 1; }

WEBROOT="$WORK/webroot"
mkdir -p "$WEBROOT/v$V1" "$WEBROOT/v$V2" "$WEBROOT/v$V3" "$WEBROOT/v$V4" "$WEBROOT/trunc" "$WEBROOT/tools"

build_variant() {  # $1 version  $2 dir-to-copy-from  $3 mode: real|bump|broken
  local version=$1 src=$2 mode=$3
  local vdir="$WORK/src-$version"
  cp -a "$src" "$vdir"
  rm -rf "$vdir/.git" "$vdir/dist"
  if [[ $mode != real ]]; then
    sed -i "s/^VERSION = \".*\"/VERSION = \"$version\"/" "$vdir/bin/serverjack"
  fi
  if [[ $mode == broken ]]; then
    sed -i '1i import sys; sys.exit(1)  # deliberately broken -- tests/managed-install.sh' "$vdir/bin/serverjack"
  fi
  ( cd "$vdir" && bash scripts/build-release.sh "$version" ) >/tmp/"$RUNID"-build.log 2>&1 \
    || { echo "build_variant $version failed:" >&2; cat /tmp/"$RUNID"-build.log >&2; exit 1; }
  rm -f /tmp/"$RUNID"-build.log
  cp "$vdir/dist/serverjack-$version.tar.gz" "$vdir/dist/serverjack-bootstrap.sh" "$vdir/dist/SHA256SUMS" \
    "$WEBROOT/v$version/"
}

say "Building test releases V1=$V1 (real) V2=$V2 (bump) V3=$V3 (broken) V4=$V4 (to be corrupted)"
build_variant "$V1" "$REPO" real
build_variant "$V2" "$REPO" bump
build_variant "$V3" "$REPO" broken
build_variant "$V4" "$REPO" bump

# One byte flipped in the SERVED archive only -- the bootstrap's own embedded
# sha256 (and SHA256SUMS) still say what the archive should have hashed to.
python3 - "$WEBROOT/v$V4/serverjack-$V4.tar.gz" <<'PY'
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
data = bytearray(p.read_bytes())
data[100] ^= 0xFF
p.write_bytes(data)
PY

# The exact truncation the spec names, plus a deliberately mid-function cut
# (the header grew past 2000 bytes, so a plain `head -c 2000` only ever lands
# inside comments -- still a valid "nothing runs" proof, but the mid-function
# cut is what actually exercises the unterminated-function-body protection
# described at the top of bootstrap/serverjack-bootstrap.sh.in).
head -c 2000 "$WEBROOT/v$V1/serverjack-bootstrap.sh" > "$WEBROOT/trunc/head2000.sh"
head -c "$(( $(wc -c < "$WEBROOT/v$V1/serverjack-bootstrap.sh") / 2 ))" \
  "$WEBROOT/v$V1/serverjack-bootstrap.sh" > "$WEBROOT/trunc/midfunc.sh"

# ------------------------------------------------------- pinned ttyd/fzf
# Parsed from install.sh itself so a future version bump here needs no edit.
# A few retries on a transient DNS/network blip -- seen in practice building
# this test -- beat failing the whole run over a hiccup unrelated to what is
# actually under test.
fetch_retry() {  # $1 url  $2 output path
  local url=$1 out=$2 n
  for n in 1 2 3 4 5; do
    curl -fsSL -o "$out" "$url" && return 0
    echo "  fetch failed ($n/5), retrying: $url" >&2
    sleep "$n"
  done
  return 1
}
TTYD_VER=$(sed -n 's/^TTYD_VER=//p' "$REPO/install.sh")
FZF_VER=$(sed -n 's/^FZF_VER=//p' "$REPO/install.sh")
say "Pre-fetching ttyd $TTYD_VER / fzf $FZF_VER (x86_64) for the test webroot"
fetch_retry "https://github.com/tsl0922/ttyd/releases/download/$TTYD_VER/ttyd.x86_64" \
  "$WEBROOT/tools/ttyd" \
  || { echo "could not download ttyd after retries" >&2; exit 1; }
fetch_retry "https://github.com/junegunn/fzf/releases/download/v$FZF_VER/fzf-$FZF_VER-linux_amd64.tar.gz" \
  "$WORK/fzf.tar.gz" \
  || { echo "could not download fzf after retries" >&2; exit 1; }
tar -xzf "$WORK/fzf.tar.gz" -C "$WEBROOT/tools" fzf
chmod 755 "$WEBROOT/tools/ttyd" "$WEBROOT/tools/fzf"

# --------------------------------------------------------------- network
docker network create "$NET" >/dev/null
docker run -d --name "$FILESRV" --network "$NET" \
  -v "$WEBROOT:/webroot:ro" -w /webroot python:3.12-slim python3 -m http.server 8080 >/dev/null
BASE_URL="http://$FILESRV:8080"

# ------------------------------------------------------------ the tester
say "Starting the systemd test container"
docker run -d --privileged --name "$TESTER" -e container=docker --network "$NET" \
  --tmpfs /run --tmpfs /run/lock --cgroupns=private "$IMG" >/dev/null

for _ in $(seq 1 30); do
  docker exec "$TESTER" systemctl is-system-running >/dev/null 2>&1 && break
  sleep 0.5
done
docker exec "$TESTER" useradd -m -s /bin/bash tester
docker exec "$TESTER" useradd -m -s /bin/bash tester2
docker exec "$TESTER" loginctl enable-linger tester
docker exec "$TESTER" loginctl enable-linger tester2
for u in tester tester2; do
  for _ in $(seq 1 30); do
    docker exec "$TESTER" test -S "/run/user/$(docker exec "$TESTER" id -u "$u")/bus" 2>/dev/null && break
    sleep 0.5
  done
done

# Cache each user's uid once -- looking it up per call (docker exec id -u)
# works but is needless overhead across the ~40 calls below.
TESTER_UID=$(docker exec "$TESTER" id -u tester)
TESTER2_UID=$(docker exec "$TESTER" id -u tester2)
run_as() {  # $1 = user ("tester"/"tester2"), remaining args = one command string
  local user=$1 uid; shift
  [[ $user == tester2 ]] && uid=$TESTER2_UID || uid=$TESTER_UID
  docker exec --user "$user" -e XDG_RUNTIME_DIR="/run/user/$uid" \
    -e SERVERJACK_RELEASE_BASE_URL="$BASE_URL" -w /tmp "$TESTER" bash -c "$*"
}

# From here on, a command failing is a test RESULT, not a script bug -- every
# scenario below expects at least one command to fail on purpose (root
# refusal, the broken release, the no-tty prompt, a truncated or corrupted
# download). -u and pipefail stay on; only -e (abort on the first nonzero)
# has to go, or the very first such check would kill the whole test run
# before recording anything.
set +e

echo "== ttyd/fzf provisioning (host-side setup)"
out=$(run_as tester "mkdir -p ~/.local/bin \
  && curl -fsSL $BASE_URL/tools/ttyd -o ~/.local/bin/ttyd \
  && curl -fsSL $BASE_URL/tools/fzf -o ~/.local/bin/fzf \
  && chmod 755 ~/.local/bin/ttyd ~/.local/bin/fzf" 2>&1)
if [[ $? -eq 0 ]]; then
  echo "  PASS pre-fetched ttyd/fzf installed into tester's ~/.local/bin"
else
  echo "  FAIL pre-fetched ttyd/fzf installed into tester's ~/.local/bin"
  echo "$out" | sed 's/^/    | /'
  failures=$((failures + 1))
fi

# ---------------------------------------------------------- (j) root refusal
echo "== (j) running the bootstrap as root is refused"
out=$(docker exec "$TESTER" bash -c "cd /tmp && curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | SERVERJACK_RELEASE_BASE_URL=$BASE_URL bash -s -- --no-serve" 2>&1); rc=$?
result "root run exits 1" "1" "$rc"
[[ $out == *"Do not run this as root"* ]] && echo "  PASS root run explains how to run as an ordinary account" \
  || { echo "  FAIL root run explains how to run as an ordinary account -- got: $out"; failures=$((failures + 1)); }
out=$(docker exec "$TESTER" bash -c 'ls /root/.local/share/serverjack 2>&1'; true)
[[ $out == *"No such file"* ]] && echo "  PASS nothing was installed under /root" \
  || { echo "  FAIL nothing was installed under /root -- got: $out"; failures=$((failures + 1)); }

# --------------------------------------------------------------- (a) install
echo "== (a) curl | bash -s -- --no-serve installs a fresh release"
out=$(run_as tester "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --no-serve" 2>&1); rc=$?
result "bootstrap exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after install" "200" "$code"
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "serverjack-ctl status reports V1" "$V1" "$code"

# ---------------------------------------------------------------- (b) rerun
echo "== (b) rerun preserves env and a shortcut"
run_as tester 'curl -s -X POST -H "Sec-Fetch-Site: same-origin" -d "cmd=echo+hi&label=testshortcut" http://127.0.0.1:7680/shortcuts/add -o /dev/null' >/dev/null
env_before=$(run_as tester 'sha256sum ~/.config/serverjack/env' | awk '{print $1}')
run_as tester 'bash ~/.local/share/serverjack/current/install.sh --no-serve' >/dev/null 2>&1
env_after=$(run_as tester 'sha256sum ~/.config/serverjack/env' | awk '{print $1}')
result "env file unchanged by rerun" "$env_before" "$env_after"
has_sc=$(run_as tester 'grep -c testshortcut ~/.config/serverjack/shortcuts.json || true')
result "shortcut survives rerun" "1" "$has_sc"

# ------------------------------------------------------- (c) update, tmux
echo "== (c) serverjack-ctl update to a bumped release, tmux session survives"
run_as tester "tmux new-session -d -s survivor 'sleep 600'"
out=$(run_as tester "~/.local/bin/serverjack-ctl update --version $V2 --yes" 2>&1); rc=$?
result "update to V2 exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version is V2 after update" "$V2" "$code"
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after update" "200" "$code"
alive=$(run_as tester "tmux has-session -t survivor 2>/dev/null && echo yes || echo no")
result "tmux session survived the update" "yes" "$alive"

# ------------------------------------------------- (d) broken update rolls back
echo "== (d) updating to a broken release auto-rolls-back"
out=$(run_as tester "~/.local/bin/serverjack-ctl update --version $V3 --yes" 2>&1); rc=$?
[[ $rc -ne 0 ]] && echo "  PASS update to the broken release exits non-zero" \
  || { echo "  FAIL update to the broken release exits non-zero -- got 0"; failures=$((failures + 1)); }
[[ $out == *"rolling back"* ]] && echo "  PASS output says it is rolling back" \
  || { echo "  FAIL output says it is rolling back -- got: $out"; failures=$((failures + 1)); }
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version is back to V2 (previous good)" "$V2" "$code"
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after the auto-rollback" "200" "$code"
alive=$(run_as tester "tmux has-session -t survivor 2>/dev/null && echo yes || echo no")
result "tmux session still survived the failed update" "yes" "$alive"

# --------------------------------------------------- (e) no-tty update refused
# Current is V2 here (post steps c/d) -- target V1 (a real change) rather
# than V2 itself, or cmd_update's "already current" no-op short-circuit
# would return 0 before ever reaching ask_confirm(), proving nothing about
# the no-tty path (found by this exact test failing for that exact reason).
echo "== (e) update with no --yes and no controlling terminal refuses cleanly"
out=$(run_as tester "~/.local/bin/serverjack-ctl update --version $V1" 2>&1); rc=$?
result "no-tty update exits 2" "2" "$rc"
[[ $out == *"no controlling terminal"* ]] && echo "  PASS explains why it refused" \
  || { echo "  FAIL explains why it refused -- got: $out"; failures=$((failures + 1)); }
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "version unchanged by the refused update" "$V2" "$code"

# ------------------------------------------------------------ (f) rollback
echo "== (f) serverjack-ctl rollback goes back to V1"
out=$(run_as tester "~/.local/bin/serverjack-ctl rollback --yes" 2>&1); rc=$?
result "rollback exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version is V1 again" "$V1" "$code"
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after rollback" "200" "$code"

# ---------------------------------------------------------- (g) truncated
# head2000.sh (the exact `head -c 2000` from the spec) lands entirely inside
# this file's now-longer header comment -- it legitimately exits 0 (there is
# nothing there to error on, and nothing there to run either). midfunc.sh
# cuts mid-function and DOES hit bash's own "unexpected end of file" syntax
# error, which is the mechanism the header comment in
# bootstrap/serverjack-bootstrap.sh.in describes -- assert that one directly.
# The real safety property either way, and what both are checked against, is
# that neither ever reaches main() and stages or installs anything.
echo "== (g) a truncated bootstrap executes nothing"
out=$(run_as tester2 "curl -fsSL $BASE_URL/trunc/midfunc.sh -o /tmp/midfunc.sh && bash /tmp/midfunc.sh" 2>&1); rc=$?
[[ $rc -ne 0 ]] && echo "  PASS midfunc.sh (cut inside a function) fails with a syntax error, not a partial run" \
  || { echo "  FAIL midfunc.sh (cut inside a function) fails with a syntax error, not a partial run -- exited 0"; failures=$((failures + 1)); }
[[ $out == *"unexpected end of file"* || $out == *"syntax error"* ]] && echo "  PASS ...and the error names it as a syntax/parse failure" \
  || { echo "  FAIL ...and the error names it as a syntax/parse failure -- got: $out"; failures=$((failures + 1)); }
run_as tester2 "curl -fsSL $BASE_URL/trunc/head2000.sh -o /tmp/head2000.sh && bash /tmp/head2000.sh" >/dev/null 2>&1
staged=$(run_as tester2 "ls ~/.local/share/serverjack/releases 2>/dev/null | wc -l")
result "no release directory exists for tester2 after either truncated attempt" "0" "$staged"
has_json=$(run_as tester2 "test -f ~/.local/share/serverjack/install.json && echo yes || echo no")
result "install.json was never written after either truncated attempt" "no" "$has_json"

# --------------------------------------------------------- (h) corrupted
echo "== (h) a corrupted archive is refused"
out=$(run_as tester2 "curl -fsSL $BASE_URL/v$V4/serverjack-bootstrap.sh | bash -s -- --no-serve" 2>&1); rc=$?
[[ $rc -ne 0 ]] && echo "  PASS corrupted-archive install exits non-zero" \
  || { echo "  FAIL corrupted-archive install exits non-zero -- got 0"; failures=$((failures + 1)); }
[[ $out == *"checksum mismatch"* ]] && echo "  PASS output names a checksum mismatch" \
  || { echo "  FAIL output names a checksum mismatch -- got: $out"; failures=$((failures + 1)); }
staged=$(run_as tester2 "ls ~/.local/share/serverjack/releases 2>/dev/null | wc -l")
result "no release directory was staged for the corrupted archive" "0" "$staged"
has_json=$(run_as tester2 "test -f ~/.local/share/serverjack/install.json && echo yes || echo no")
result "install.json was never written for the corrupted archive" "no" "$has_json"

# ------------------------------------------------------------ (i) uninstall
echo "== (i) serverjack-ctl uninstall --yes leaves config and tmux"
out=$(run_as tester "~/.local/bin/serverjack-ctl uninstall --yes" 2>&1); rc=$?
result "uninstall exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
has_env=$(run_as tester "test -f ~/.config/serverjack/env && echo yes || echo no")
result "~/.config/serverjack/env kept" "yes" "$has_env"
has_sc=$(run_as tester "test -f ~/.config/serverjack/shortcuts.json && echo yes || echo no")
result "~/.config/serverjack/shortcuts.json kept" "yes" "$has_sc"
share_gone=$(run_as tester "test -d ~/.local/share/serverjack && echo present || echo gone")
result "~/.local/share/serverjack removed" "gone" "$share_gone"
alive=$(run_as tester "tmux has-session -t survivor 2>/dev/null && echo yes || echo no")
result "tmux session survives uninstall" "yes" "$alive"
unit_gone=$(run_as tester "systemctl --user list-unit-files serverjack.service 2>/dev/null | grep -c serverjack.service || true")
result "the serverjack unit file is gone" "0" "$unit_gone"

echo
if (( failures > 0 )); then
  echo "$failures managed-install check(s) failed" >&2
fi
exit $(( failures > 0 ))
