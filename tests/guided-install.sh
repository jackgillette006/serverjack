#!/usr/bin/env bash
# shellcheck disable=SC2088
# (same reasoning as tests/managed-install.sh's identical disable: this file
# is full of "~/..." inside double-quoted strings destined for a FRESH shell
# inside the container, where they expand normally -- never the local tilde
# SC2088 warns about)
#
# Container test for guided-install-plan step 4 ("serverjack-setup"): the
# prerequisites/Tailscale/allow-list/shared-machine flow that now sits
# between the bootstrap and install.sh. Needs docker able to run
# --privileged containers with real systemd -- if it can't, this prints why
# and exits 0 (a skip, not a failure). Optional, host-side, wired into
# `bash tests/run.sh` (see there).
#
# Every prompt is driven through a REAL pty (tests/guided-install-driver.py,
# stdlib Python, spawns `docker exec -i ... script -qfc '...' /dev/null` --
# `script` is what allocates the pty the child sees as /dev/tty) -- nothing
# here assumes a prompt appeared or was answered; the driver waits for the
# exact text serverjack-setup printed before sending a reply, and the full
# transcript is always logged.
#
# What it proves, one Linux account per scenario (fresh managed-install
# state, same reasoning tests/managed-install.sh uses tester/tester2) on a
# Debian 13 systemd container with tmux, iproute2 (ss) and ca-certificates
# DELIBERATELY missing at image build time, and a fake `tailscale` binary
# (tests/fixtures/fake-tailscale.sh, state read/written under
# ~/.faketailscale/) standing in for the real thing everywhere except the
# very first scenario:
#
#   (a) missing prerequisites, offer refused: exits 1, nothing installed
#   (b) missing prerequisites, offer accepted, then Tailscale entirely
#       missing (hidden from PATH) and "skip serve" chosen: completes with
#       --no-serve, prints the local URL and the remaining step
#   (c) no controlling terminal: clean stop, exit 2, nothing changed
#   (d) running serverjack-setup itself (not through the bootstrap) as root:
#       refused before anything is written
#   (e) an unsupported OS (faked /etc/os-release via a test-only env hook):
#       refused with the manual-install fallback
#   (f) fake tailscale logged out, "up" brings it to Running (URL surfaced,
#       polled), untagged with one login: allow-list defaults to it
#   (g) fake tailscale already running and TAGGED: allow-list is required,
#       not offered as optional
#   (h) fake tailscale running, an https:443 serve mapping already proxying
#       somewhere else: offered and given an alternate --https-port
#   (i) "other accounts share this machine?" yes selects --unix
#   (j) re-running setup (via `serverjack-ctl setup`) on (f)'s now-installed
#       account, choosing "nothing": env file and units are untouched
#
# ttyd and fzf are pre-fetched on the HOST (real internet, proven by the
# setup steps) at the exact pinned versions install.sh expects, then served
# from the same private webroot as the release itself -- same reasoning as
# tests/managed-install.sh.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)

RUNID="sjgi-$$-$(date +%s)"
IMG="serverjack-guided-install-test:latest"
NET="$RUNID-net"
FILESRV="$RUNID-filesrv"
TESTER="$RUNID-tester"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-guided-install.XXXXXX")
# 755, not 700: bind-mounted read-write into the container at /work (below)
# so run_dialogue() can hand each scenario's payload to a DIFFERENT test
# account as a plain file (`bash /work/payload-<label>.sh`) rather than
# re-quoting it through docker exec / script -c -- nesting that command
# through two more shells is exactly what produced a real, found-by-running
# bug (a `"$?"` meant for the innermost shell got quote-closed early by an
# outer layer and expanded at the wrong time). Every account needs to
# traverse and read it, hence 755 here and 644 on the payload files below;
# nothing under here is sensitive (the webroot it also holds is served
# over plain HTTP to the test container regardless).
chmod 755 "$WORK"
DRIVER="$REPO/tests/guided-install-driver.py"

failures=0
result() {  # $1 label, $2 expected, $3 got
  if [[ $3 == "$2" ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1  -- got $3, wanted $2"
    failures=$((failures + 1))
  fi
}
contains() {  # $1 label, $2 haystack, $3 needle
  if [[ $2 == *"$3"* ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1  -- expected to find: $3"
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
  echo "docker not found -- skipping the guided-install container test" >&2
  exit 0
fi
if ! docker run --rm --privileged -e container=docker debian:13-slim true >/dev/null 2>&1; then
  echo "docker cannot run --privileged containers here -- skipping the guided-install container test" >&2
  exit 0
fi

# ------------------------------------------------------------- test image
# tmux, iproute2 (ss) and ca-certificates deliberately absent -- that is
# what gives scenarios (a)/(b) real missing prerequisites to offer. curl,
# python3 and sudo ARE pre-installed: curl is needed to fetch the bootstrap
# in the first place (the plan document is explicit that curl/HTTPS are a
# precondition for reaching an installer at all, not something it can fix
# for itself), and python3/sudo are needed for this fixture's own plumbing
# regardless of what the test is proving.
say() { printf '\033[1m%s\033[0m\n' "$*"; }
say "Building the test image"
cp "$REPO/tests/fixtures/fake-tailscale.sh" "$WORK/fake-tailscale.sh"
cat > "$WORK/Dockerfile" <<'EOF'
FROM debian:13-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus dbus-user-session libpam-systemd \
      curl python3 sudo procps hostname less \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY fake-tailscale.sh /usr/local/bin/tailscale
RUN chmod 755 /usr/local/bin/tailscale
STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
EOF
docker build -t "$IMG" -f "$WORK/Dockerfile" "$WORK" >/tmp/"$RUNID"-build.log 2>&1 \
  || { echo "image build failed:" >&2; cat /tmp/"$RUNID"-build.log >&2; exit 1; }
rm -f /tmp/"$RUNID"-build.log

# ------------------------------------------------------------ the release
V1=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$REPO/bin/serverjack")
[[ -n $V1 ]] || { echo "could not read VERSION from bin/serverjack" >&2; exit 1; }
WEBROOT="$WORK/webroot"
mkdir -p "$WEBROOT/v$V1" "$WEBROOT/tools"
say "Building release $V1 for the test webroot"
( cd "$REPO" && bash scripts/build-release.sh "$V1" ) >/tmp/"$RUNID"-build.log 2>&1 \
  || { echo "build-release.sh failed:" >&2; cat /tmp/"$RUNID"-build.log >&2; exit 1; }
rm -f /tmp/"$RUNID"-build.log
cp "$REPO/dist/serverjack-$V1.tar.gz" "$REPO/dist/serverjack-bootstrap.sh" "$REPO/dist/SHA256SUMS" \
  "$WEBROOT/v$V1/"

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

say "Starting the systemd test container"
docker run -d --privileged --name "$TESTER" -e container=docker --network "$NET" \
  --tmpfs /run --tmpfs /run/lock --cgroupns=private \
  -v "$REPO:/srv/serverjack:ro" -v "$WORK:/work" \
  "$IMG" >/dev/null

for _ in $(seq 1 30); do
  docker exec "$TESTER" systemctl is-system-running >/dev/null 2>&1 && break
  sleep 0.5
done

USERS=(prereq_a prereq_b notty ts1 ts2 ts3 ts4)
for u in "${USERS[@]}"; do
  docker exec "$TESTER" useradd -m -s /bin/bash "$u"
  docker exec "$TESTER" loginctl enable-linger "$u"
  echo "$u ALL=(ALL) NOPASSWD:ALL" | docker exec -i "$TESTER" tee -a /etc/sudoers.d/guided-install-tests >/dev/null
done
docker exec "$TESTER" chmod 440 /etc/sudoers.d/guided-install-tests
for u in "${USERS[@]}"; do
  for _ in $(seq 1 30); do
    docker exec "$TESTER" test -S "/run/user/$(docker exec "$TESTER" id -u "$u")/bus" 2>/dev/null && break
    sleep 0.5
  done
done

# faketailscale state for a user: $1 user  $2 state(needslogin|running)
# $3 login  $4 tagged(0|1)  $5 foreign(0|1)
set_ts_state() {
  local user=$1 state=$2 login=$3 tagged=$4 foreign=$5
  docker exec --user "$user" "$TESTER" bash -c "
    mkdir -p ~/.faketailscale
    echo '$state' > ~/.faketailscale/state
    echo '$login' > ~/.faketailscale/login
    if [[ $tagged == 1 ]]; then touch ~/.faketailscale/tagged; else rm -f ~/.faketailscale/tagged; fi
    if [[ $foreign == 1 ]]; then touch ~/.faketailscale/foreign; else rm -f ~/.faketailscale/foreign; fi
  "
}
reset_operator() { docker exec "$TESTER" rm -f /etc/faketailscale-operator; }

env_val() {  # $1 user  $2 key -- reads ~/.config/serverjack/env inside the container
  docker exec --user "$1" "$TESTER" bash -c "sed -n 's/^$2=//p' ~/.config/serverjack/env 2>/dev/null | tail -1 | tr -d '\"'"
}

# Runs one interactive dialogue via the pty driver. $1 label  $2 user
# $3 timeout-seconds PER EXCHANGE (an earlier slow step, e.g. `apt-get
# install`, must not eat into a later prompt's own budget)  $4 payload
# command  $5 extra `docker exec -e` args (a single string, word-split; may
# be empty)  $6 exchanges JSON (heredoc
# content, the interactive part only -- a final wait for the real exit code
# is appended automatically, see below). Sets DLG_RC (the payload's real
# exit code, or -1 if it can't be found) and prints PASS/FAIL for the
# dialogue completing as scripted, plus the transcript tail either way.
#
# The payload is written to a FILE under the bind-mounted $WORK (/work in
# the container) and run as `bash /work/payload-<label>.sh`, rather than
# handed to `docker exec ... bash -c "script -qfc \"...\" ..."` as an
# increasingly-quoted string -- nesting a command containing its own
# double-quoted "$?" through two more layers of double-quoting is exactly
# what produced a real bug here: the inner quote got closed early by the
# outer layer and $? was expanded at the wrong time (before the payload
# had even run), found by this test actually failing that way, not assumed.
# A plain file sidesteps re-quoting entirely.
#
# Separately: `script -qfc CMD LOGFILE` always returns 0 itself regardless
# of CMD's exit status (also verified directly, not assumed), so the outer
# docker-exec/script exit code is meaningless either way -- the script
# prints its own real exit code as a marker line, which is what DLG_RC and
# the auto-appended final exchange are read from.
run_dialogue() {
  local label=$1 user=$2 timeout=$3 payload=$4 extra_env=$5
  local exfile="$WORK/ex-$label.json"
  local raw="$WORK/ex-$label.raw.json"
  cat > "$raw"
  python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    exchanges = json.load(fh)
exchanges.append(["GUIDED_TEST_EXIT:", None])
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(exchanges, fh)
' "$raw" "$exfile"
  cat > "$WORK/payload-$label.sh" <<PAYLOAD
#!/bin/bash
( $payload )
rc=\$?
printf 'GUIDED_TEST_EXIT:%d\n' "\$rc"
PAYLOAD
  chmod 644 "$WORK/payload-$label.sh"
  local -a extra=()
  # shellcheck disable=SC2206 # deliberate word-splitting of "-e K=V -e K2=V2"
  [[ -n $extra_env ]] && extra=($extra_env)
  local logfile="$WORK/log-$label.txt"
  if python3 "$DRIVER" "$timeout" "$exfile" -- \
      docker exec -i --user "$user" "${extra[@]}" "$TESTER" \
      script -qfc "bash /work/payload-$label.sh" /dev/null \
      > "$logfile" 2>&1; then
    echo "  PASS dialogue($label) completed as scripted"
  else
    echo "  FAIL dialogue($label) did not complete as scripted -- see $logfile"
    failures=$((failures + 1))
  fi
  # A real pty (script) echoes CRLF, not bare LF -- strip it, or "1" from the
  # marker line never string-equals the "1" a caller compares it against.
  DLG_RC=$(sed -n 's/^GUIDED_TEST_EXIT://p' "$logfile" | tail -1 | tr -d '\r')
  [[ -n $DLG_RC ]] || DLG_RC=-1
  echo "== $label transcript (tail) =="
  tail -40 "$logfile" | sed 's/^/    | /'
}

# From here on, a command failing is a test RESULT, not a script bug -- every
# scenario below expects at least one command (or dialogue) to fail on
# purpose (root refusal, an unsupported OS, no controlling terminal, a
# refused prereq offer), and under `set -e` even `out=$(cmd); rc=$?` aborts
# the whole script the moment `cmd` inside the substitution returns nonzero
# -- the assignment's own exit status IS that of the substitution. -u and
# pipefail stay on; only -e goes, same reasoning as tests/managed-install.sh.
set +e

echo "================================================================"
echo "(d) running serverjack-setup itself as root is refused"
out=$(docker exec --user root "$TESTER" bash -c 'bash /srv/serverjack/bin/serverjack-setup --no-serve' 2>&1); rc=$?
result "root run exits 1" "1" "$rc"
contains "root run explains how to run as an ordinary account" "$out" "Do not run this as root"
out=$(docker exec "$TESTER" bash -c 'ls /root/.local/share/serverjack 2>&1'; true)
contains "nothing was installed under /root" "$out" "No such file"

echo "================================================================"
echo "(e) an unsupported OS is refused, with the manual-install fallback"
out=$(docker exec --user prereq_a -e SERVERJACK_SETUP_TEST_OS_RELEASE=/tmp/fake-os-release "$TESTER" \
  bash -c 'printf "ID=fedora\nVERSION_ID=\"39\"\n" > /tmp/fake-os-release && bash /srv/serverjack/bin/serverjack-setup --no-serve' 2>&1); rc=$?
result "unsupported OS exits 2" "2" "$rc"
contains "names the unsupported distribution" "$out" "Unsupported distribution: fedora 39"
contains "offers the manual git-checkout path" "$out" "bash serverjack/install.sh"

echo "================================================================"
echo "(a) missing prerequisites, offer refused"
run_dialogue prereq_a prereq_a 30 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Install them now?", "n"],
 ["Not installing. Run this yourself", null]]
JSON
result "prereq refusal exits 1" "1" "$DLG_RC"
out=$(docker exec --user prereq_a "$TESTER" bash -c 'command -v tmux || echo "no tmux"' 2>&1)
contains "tmux still not installed after refusal" "$out" "no tmux"

echo "================================================================"
echo "(b) missing prerequisites accepted, then Tailscale missing + skip serve"
run_dialogue prereq_b prereq_b 150 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7680" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL -e PATH=/usr/sbin:/usr/bin:/sbin:/bin" <<'JSON'
[["Install them now?", "y"],
 ["Installed: ", null],
 ["Tailscale is not installed.", null],
 ["Publish with tailscale serve", "n"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["not yet reachable from your phone", null]]
JSON
result "prereq accept + skip-serve exits 0" "0" "$DLG_RC"
out=$(docker exec "$TESTER" bash -c 'command -v tmux && command -v ss' 2>&1)
contains "tmux now installed (container-wide)" "$out" "/usr/bin/tmux"
contains "iproute2 (ss) now installed" "$out" "ss"
[[ $(env_val prereq_b SERVERJACK_LISTEN) == tcp ]] && echo "  PASS prereq_b installed tcp" \
  || { echo "  FAIL prereq_b installed tcp"; failures=$((failures + 1)); }

echo "================================================================"
echo "(c) no controlling terminal: clean stop, exit 2, nothing changed"
# Own port (7740), same reasoning as ts1-ts4: this shares ONE container/
# network-namespace with every other scenario, so the default 7680 would
# collide with whichever earlier scenario is still running there.
out=$(docker exec --user notty -e SERVERJACK_RELEASE_BASE_URL="$BASE_URL" "$TESTER" \
  bash -c "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7740" 2>&1 </dev/null); rc=$?
result "no-tty run exits 2" "2" "$rc"
[[ $rc != 2 ]] && echo "$out" | sed 's/^/    | /'
contains "explains there is no controlling terminal" "$out" "No controlling terminal is available"
out=$(docker exec --user notty "$TESTER" bash -c 'test -f ~/.config/systemd/user/serverjack.service && echo present || echo absent' 2>&1)
result "no unit installed for notty" "absent" "$out"

echo "================================================================"
echo "(f) fake tailscale logged out -> Running after 'up'; untagged, allow defaulted"
reset_operator
set_ts_state ts1 needslogin "alice@github" 0 0
run_dialogue ts1 ts1 90 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7690" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Tailscale is installed but not signed in", null],
 ["Publish with tailscale serve", "y"],
 ["Open this URL to finish signing in:", null],
 ["Tailscale is running.", null],
 ["Detected tailnet login: alice@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["Run it now?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts1 exits 0" "0" "$DLG_RC"
[[ $(env_val ts1 SERVERJACK_ALLOW) == "alice@github" ]] && echo "  PASS ts1 allow-list = alice@github" \
  || { echo "  FAIL ts1 allow-list -- got $(env_val ts1 SERVERJACK_ALLOW)"; failures=$((failures + 1)); }
[[ $(env_val ts1 SERVERJACK_PORT) == 7690 ]] && echo "  PASS ts1 port = 7690" \
  || { echo "  FAIL ts1 port -- got $(env_val ts1 SERVERJACK_PORT)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(g) fake tailscale running and TAGGED: allow-list required"
reset_operator
set_ts_state ts2 running "bob@github" 1 0
run_dialogue ts2 ts2 60 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7700" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["This node is tagged", null],
 ["allow-list is required", "carol@github"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["Run it now?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts2 exits 0" "0" "$DLG_RC"
[[ $(env_val ts2 SERVERJACK_ALLOW) == "carol@github" ]] && echo "  PASS ts2 allow-list = carol@github" \
  || { echo "  FAIL ts2 allow-list -- got $(env_val ts2 SERVERJACK_ALLOW)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(h) an existing foreign serve mapping on 443 is offered an alternate port"
reset_operator
set_ts_state ts3 running "dave@github" 0 1
run_dialogue ts3 ts3 60 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7710" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: dave@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["Run it now?", "y"],
 ["already proxies to", null],
 ["Use a different HTTPS port", "8443"],
 ["Using HTTPS port 8443 instead.", null],
 ["not yet reachable from your phone", null]]
JSON
result "ts3 exits 0" "0" "$DLG_RC"
[[ $(env_val ts3 SERVERJACK_HTTPS_PORT) == 8443 ]] && echo "  PASS ts3 https-port = 8443" \
  || { echo "  FAIL ts3 https-port -- got $(env_val ts3 SERVERJACK_HTTPS_PORT)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(i) 'other accounts share this machine?' yes selects --unix"
reset_operator
set_ts_state ts4 running "erin@github" 0 0
run_dialogue ts4 ts4 60 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7720" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: erin@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "y"],
 ["Run it now?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts4 exits 0" "0" "$DLG_RC"
[[ $(env_val ts4 SERVERJACK_LISTEN) == unix ]] && echo "  PASS ts4 listen = unix" \
  || { echo "  FAIL ts4 listen -- got $(env_val ts4 SERVERJACK_LISTEN)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(j) rerun on (f)'s account via serverjack-ctl setup, choosing 'nothing'"
env_before=$(docker exec --user ts1 "$TESTER" bash -c 'sha256sum ~/.config/serverjack/env' | awk '{print $1}')
run_dialogue rerun ts1 30 '~/.local/bin/serverjack-ctl setup' "" <<'JSON'
[["already installed here as a managed release", null],
 ["Choice [1-4, default 4]:", ""],
 ["Leaving everything as it is.", null]]
JSON
result "rerun exits 0" "0" "$DLG_RC"
env_after=$(docker exec --user ts1 "$TESTER" bash -c 'sha256sum ~/.config/serverjack/env' | awk '{print $1}')
result "env file unchanged by 'nothing'" "$env_before" "$env_after"
active=$(docker exec --user ts1 "$TESTER" bash -c 'systemctl --user is-active serverjack 2>/dev/null')
result "serverjack still active after 'nothing'" "active" "$active"

echo
if (( failures > 0 )); then
  echo "$failures guided-install check(s) failed" >&2
fi
exit $(( failures > 0 ))
