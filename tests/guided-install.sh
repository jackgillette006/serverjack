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
#   (k) `serverjack-ctl uninstall` removes the tailscale serve mapping a
#       fresh publish created
#   (l) a root-step prompt (tailscale operator) answered with a bare Enter
#       (its default) never runs sudo (a fake sudo wrapper on PATH records
#       every invocation)
#   (m) rerun on (f)'s account again, choosing "1) update": proves
#       `serverjack-ctl setup` handing off to serverjack-setup, which in
#       turn shells out to `serverjack-ctl update`, does not deadlock on
#       the outer command's own lock
#   (n) a deliberately broken release (unit crash-loops, /healthz never
#       answers) still gets the health-check failure diagnostic and the
#       journalctl hint, instead of verify_and_report dying silently on an
#       unguarded `is-active | paste` pipeline under pipefail
#   (o) rerunning setup on a real git-checkout install (installed directly
#       via install.sh, never through the bootstrap) shows the same rerun
#       menu as a managed install, instead of the old unconditional refusal
#   (p) WSL (faked via WSL_DISTRO_NAME): the untouched default port (7680)
#       gets step7b_wsl_port's offer, and a bare Enter (its "y" default)
#       switches the real install to --port 7690
#   (q) WSL again, but --port given explicitly: no offer at all, and the
#       requested port is what's actually installed
#
# (f)-(i) each also assert the tailscale serve MAPPING itself exists
# afterward (`tailscale serve status`, via the fake's now-real, mutable
# ServeConfig -- see tests/fixtures/fake-tailscale.sh), not only that
# serverjack-setup printed a particular message.
#
# ttyd and fzf are pre-fetched on the HOST (real internet, proven by the
# setup steps) at the exact pinned versions install.sh expects, then copied
# straight into every test account's ~/.local/bin before it runs anything
# (so install.sh's own version check short-circuits and never has to reach
# github.com itself) -- same reasoning, and the same fix for the same
# flakiness, as tests/managed-install.sh's provision_ttyd_fzf().
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
cp "$REPO/tests/fixtures/fake-sudo-wrapper.sh" "$WORK/fake-sudo-wrapper.sh"
cp "$REPO/tests/fixtures/prestart-hook.sh" "$WORK/prestart-hook.sh"
cat > "$WORK/Dockerfile" <<'EOF'
FROM debian:13-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus dbus-user-session libpam-systemd \
      curl python3 sudo procps hostname less \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY fake-tailscale.sh /usr/local/bin/tailscale
RUN chmod 755 /usr/local/bin/tailscale
# NOT on the default PATH (see the file's own header) -- only the scenario
# that needs it prepends /opt/fake-sudo-bin.
COPY fake-sudo-wrapper.sh /opt/fake-sudo-bin/sudo
RUN chmod 755 /opt/fake-sudo-bin/sudo
COPY prestart-hook.sh /usr/local/bin/prestart-hook.sh
RUN chmod 755 /usr/local/bin/prestart-hook.sh
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

# A second, deliberately broken release for scenario (n) below (finding 3):
# bin/serverjack exits immediately, so the unit crash-loops (Restart=on-
# failure) and never answers /healthz -- exactly what verify_and_report()
# must survive without the old pipefail bug silently swallowing it.
V2="9.9.5-guided-broken-test"
mkdir -p "$WEBROOT/v$V2"
say "Building a deliberately broken release $V2 for the finding-3 scenario"
V2DIR="$WORK/src-$V2"
cp -a "$REPO" "$V2DIR"
rm -rf "$V2DIR/.git" "$V2DIR/dist"
sed -i "s/^VERSION = \".*\"/VERSION = \"$V2\"/" "$V2DIR/bin/serverjack"
sed -i '1i import sys; sys.exit(1)  # deliberately broken -- tests/guided-install.sh finding 3' "$V2DIR/bin/serverjack"
( cd "$V2DIR" && bash scripts/build-release.sh "$V2" ) >/tmp/"$RUNID"-build2.log 2>&1 \
  || { echo "build-release.sh (broken variant) failed:" >&2; cat /tmp/"$RUNID"-build2.log >&2; exit 1; }
rm -f /tmp/"$RUNID"-build2.log
cp "$V2DIR/dist/serverjack-$V2.tar.gz" "$V2DIR/dist/serverjack-bootstrap.sh" "$V2DIR/dist/SHA256SUMS" \
  "$WEBROOT/v$V2/"

fetch_retry() {  # $1 url  $2 output path
  local url=$1 out=$2 n
  for n in 1 2 3 4 5; do
    curl -fsSL -o "$out" "$url" && return 0
    echo "  fetch failed ($n/5), retrying: $url" >&2
    sleep "$n"
  done
  return 1
}
TTYD_VER=$(sed -n 's/^TTYD_VER=//p' "$REPO/scripts/fetch-ttyd.sh")
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

USERS=(prereq_a prereq_b notty ts1 ts2 ts3 ts4 ts5 ts6 ts7 ts8 ts9 ts10 ts11 wslacc wslflag)
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

# Pre-fetched ttyd/fzf were already proven against real internet (see the
# host-side fetch above) -- copy them straight into every account's
# ~/.local/bin (from the same webroot bind-mounted at /work, so no docker
# cp or second download is needed) so install.sh's own version check
# ("$BIN/ttyd" --version ... | grep -q ...) short-circuits and never needs
# to reach github.com itself. Without this, EVERY account's own install.sh
# run independently re-fetches ttyd/fzf from real GitHub -- same reasoning
# as tests/managed-install.sh's provision_ttyd_fzf(), and why that file
# doesn't have this flakiness: a transient DNS/network blip mid-run used to
# fail scenarios that have nothing to do with networking at all.
for u in "${USERS[@]}"; do
  docker exec --user "$u" "$TESTER" bash -c \
    'mkdir -p ~/.local/bin && cp /work/webroot/tools/ttyd /work/webroot/tools/fzf ~/.local/bin/ && chmod 755 ~/.local/bin/ttyd ~/.local/bin/fzf'
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

# The fake tailscale now tracks a real, mutable ServeConfig (see
# tests/fixtures/fake-tailscale.sh) -- this actually exercises the mapping
# `tailscale serve` really made, not just the failure string every guided
# publish scenario used to be limited to asserting (the fake used to have no
# state for a successful publish at all).
check_serve_mapping() {  # $1 label  $2 user  $3 https_port  $4 expected backend substring
  local label=$1 user=$2 https=$3 want=$4 out
  out=$(docker exec --user "$user" "$TESTER" bash -c 'tailscale serve status' 2>&1)
  contains "$label: serve status shows https port $https" "$out" ":$https "
  contains "$label: serve status proxies to $want" "$out" "proxy $want"
}

# B2: the negative of check_serve_mapping -- proves a mapping is REALLY gone
# (this installation's own remove_owned_mapping actually ran and succeeded),
# not merely that install.sh was told --no-serve / a different port while
# the old tailscale serve route kept proxying here regardless.
check_no_serve_mapping() {  # $1 label  $2 user  $3 https_port
  local label=$1 user=$2 https=$3 out
  out=$(docker exec --user "$user" "$TESTER" bash -c 'tailscale serve status' 2>&1)
  if [[ $out == *":$https "* ]]; then
    echo "  FAIL $label -- https port $https still has a mapping:"
    echo "$out" | sed 's/^/    | /'
    failures=$((failures + 1))
  else
    echo "  PASS $label"
  fi
}

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
# C1: the bootstrap's OWN prerequisite-floor check (ca-certificates is on
# both lists -- the bootstrap needs it for its own HTTPS downloads, setup's
# step 3 needs it too) now runs FIRST and asks its own, differently-worded
# prompt ("...with sudo?") -- accepted here (a real `sudo apt-get install`,
# this container has real internet) so the bootstrap can proceed far enough
# to reach the scenario this test actually targets: setup's OWN step 3
# prompt for tmux/ss, declined.
run_dialogue prereq_a prereq_a 60 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Install them now with sudo?", "y"],
 ["Install them now?", "n"],
 ["Not installing. Run this yourself", null]]
JSON
result "prereq refusal exits 1" "1" "$DLG_RC"
out=$(docker exec --user prereq_a "$TESTER" bash -c 'command -v tmux || echo "no tmux"' 2>&1)
contains "tmux still not installed after refusal" "$out" "no tmux"

echo "================================================================"
echo "(b) missing prerequisites accepted, then Tailscale missing + skip serve"
# C1's bootstrap-level floor check (scenario (a) above, accepted) already
# installed ca-certificates SYSTEM-WIDE (apt-get is machine-wide, not
# per-account) -- so by the time THIS scenario's bootstrap runs, ca-
# certificates is no longer missing and its own "...with sudo?" prompt
# never fires at all; only setup's own step-3 prompt (tmux, iproute2) does.
# (Found the hard way: expecting the bootstrap's prompt here too made the
# driver wait the full timeout for text that was never going to appear,
# get SIGKILLed, and its orphaned `apt-get install` kept running in the
# background -- cascading into failures on every later, unrelated
# scenario. If scenario (a) is ever removed or reordered, this needs its
# own "Install them now with sudo?" step back.)
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
# prereq_b is never referenced again after the two checks just above --
# free the port it holds (7680) now, by hand, since (p) below needs to see
# 7680 genuinely free to exercise step7b_wsl_port's real "still the
# untouched default" condition (check_foreign_port() runs first, ahead of
# any prompt, and checks the OS-level bind, not any per-account state).
docker exec --user prereq_b "$TESTER" bash -c '~/.local/bin/serverjack-ctl uninstall --yes' >/dev/null 2>&1 \
  || { echo "  FAIL could not free prereq_b's port 7680 for scenario (p)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(p) WSL (faked via WSL_DISTRO_NAME): offers 7690 for the untouched default port"
# Prerequisites (tmux/ss/ca-certificates) are already fixed system-wide by
# (a)/(b) above, so this account's bootstrap goes straight to serverjack-
# setup's own prompts -- --tcp/--no-serve are given so the ONLY remaining
# question is step7b_wsl_port's, isolating exactly the thing this proves.
# --port is deliberately NOT given: the whole point is the untouched
# default (7680), which is why prereq_b's port had to be freed just above.
run_dialogue wslacc wslacc 60 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --no-serve --tcp" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL -e WSL_DISTRO_NAME=Debian" <<'JSON'
[["This looks like WSL", null],
 ["Use port 7690 instead?", ""],
 ["not yet reachable from your phone", null]]
JSON
result "wslacc exits 0" "0" "$DLG_RC"
contains "wslacc: names Windows Delivery Optimization" "$(cat "$WORK/log-wslacc.txt" 2>/dev/null)" "Windows Delivery Optimization"
contains "wslacc: install.sh was actually run with --port 7690" "$(cat "$WORK/log-wslacc.txt" 2>/dev/null)" "Running: bash install.sh --tcp --no-serve --port 7690"
[[ $(env_val wslacc SERVERJACK_PORT) == 7690 ]] && echo "  PASS wslacc port = 7690" \
  || { echo "  FAIL wslacc port -- got $(env_val wslacc SERVERJACK_PORT)"; failures=$((failures + 1)); }
# Never referenced again -- free its port (7690) now, the same reasoning as
# prereq_b just above: (f)'s ts1, below, needs 7690 too.
docker exec --user wslacc "$TESTER" bash -c '~/.local/bin/serverjack-ctl uninstall --yes' >/dev/null 2>&1 \
  || { echo "  FAIL could not free wslacc's port 7690 for scenario (f)"; failures=$((failures + 1)); }

echo "================================================================"
echo "(q) WSL again, but --port given explicitly: no offer, no --port rewrite"
# Fully resolved by flags (--no-serve --tcp --port 7681), so this never
# touches /dev/tty at all (see bin/serverjack-setup's own header comment on
# that contract) -- a plain, non-interactive docker exec, like (c)'s notty
# above, rather than the pty driver.
out=$(docker exec --user wslflag -e SERVERJACK_RELEASE_BASE_URL="$BASE_URL" -e WSL_DISTRO_NAME=Debian "$TESTER" \
  bash -c "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --no-serve --tcp --port 7681" 2>&1 </dev/null); rc=$?
result "wslflag exits 0" "0" "$rc"
[[ $rc != 0 ]] && echo "$out" | sed 's/^/    | /'
if [[ $out == *"This looks like WSL"* ]]; then
  echo "  FAIL wslflag: step7b_wsl_port prompted even though --port was given"
  failures=$((failures + 1))
else
  echo "  PASS wslflag: no WSL port prompt (an explicit --port answers it)"
fi
[[ $(env_val wslflag SERVERJACK_PORT) == 7681 ]] && echo "  PASS wslflag port = 7681 (the requested one, untouched)" \
  || { echo "  FAIL wslflag port -- got $(env_val wslflag SERVERJACK_PORT)"; failures=$((failures + 1)); }

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
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL -e SERVERJACK_TEST_PRESTART_HOOK=/usr/local/bin/prestart-hook.sh" <<'JSON'
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
check_serve_mapping ts1 ts1 443 "http://127.0.0.1:7690"
# B1: the allow-list must already be on disk at the moment install.sh first
# starts a unit or could publish anything -- not written afterward by a
# separate restart, which left a window with no restriction in force.
hook_out=$(docker exec --user ts1 "$TESTER" bash -c 'cat ~/.prestart-hook-result 2>&1')
result "ts1 B1: SERVERJACK_ALLOW already on disk before units start" "ALLOW_PRESENT" "$hook_out"
# B1: a request from this account's own loopback still 403s once ALLOW is
# set -- the peer isn't tailscaled (root), so the identity header is never
# even read (see bin/serverjack's identity_ok()); this proves the freshly
# published instance is NOT answering everyone the moment it's up, which is
# exactly the window B1 closes. (This is also why the app's own report can
# only ever say "the app answers locally", not "unauthorized users are
# denied" -- see C3: a tagged/self request tells you nothing about what a
# phone sees.)
code=$(docker exec --user ts1 "$TESTER" curl -s -o /dev/null -w '%{http_code}' \
  -H 'Tailscale-User-Login: mallory@github' http://127.0.0.1:7690/)
result "ts1 B1: request with an identity header still 403s (ALLOW enforced immediately)" "403" "$code"

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
check_serve_mapping ts2 ts2 443 "http://127.0.0.1:7700"

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
# The pre-existing foreign mapping on 443 must still be there too -- ts3
# picked 8443 specifically to avoid disturbing it.
check_serve_mapping "ts3 (own, 8443)" ts3 8443 "http://127.0.0.1:7710"
check_serve_mapping "ts3 (foreign, 443, untouched)" ts3 443 "http://127.0.0.1:9999"

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
 ["tailscale serve needs root", null],
 ["Run it now?", "y"],
 ["Published:", null],
 ["not yet reachable from your phone", null]]
JSON
result "ts4 exits 0" "0" "$DLG_RC"
[[ $(env_val ts4 SERVERJACK_LISTEN) == unix ]] && echo "  PASS ts4 listen = unix" \
  || { echo "  FAIL ts4 listen -- got $(env_val ts4 SERVERJACK_LISTEN)"; failures=$((failures + 1)); }
ts4_uid=$(docker exec "$TESTER" id -u ts4)
check_serve_mapping ts4 ts4 443 "unix:/run/user/$ts4_uid/serverjack/web.sock"

echo "================================================================"
echo "(s) C4: declining the --unix serve root step leaves the install"
echo "    local-only, without ever invoking sudo tailscale serve"
reset_operator
set_ts_state ts11 running "hank@github" 0 0
run_dialogue ts11 ts11 150 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7732" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL -e PATH=/opt/fake-sudo-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: hank@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "y"],
 ["Run it now?", "y"],
 ["tailscale serve needs root", null],
 ["Run it now?", "n"]]
JSON
result "ts11 exits 0 (declining the unix-serve step doesn't abort the install)" "0" "$DLG_RC"
sudo_log=$(docker exec --user ts11 "$TESTER" bash -c 'cat ~/.fake-sudo.log 2>/dev/null || true')
[[ $sudo_log != *"tailscale serve"* ]] && echo "  PASS ts11: sudo tailscale serve was never invoked (declined)" \
  || { echo "  FAIL ts11: sudo tailscale serve was invoked despite declining -- got: $sudo_log"; failures=$((failures + 1)); }
out=$(docker exec --user ts11 "$TESTER" bash -c 'tailscale serve status' 2>&1)
[[ $out != *"unix:"* ]] && echo "  PASS ts11: no unix: mapping was published" \
  || { echo "  FAIL ts11: a unix: mapping exists despite declining -- got: $out"; failures=$((failures + 1)); }

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
# Needs its own XDG_RUNTIME_DIR (systemctl --user can't find the right bus
# without it) -- every other systemctl --user check in this file goes
# through serverjack-setup, which sets a sane default internally; this is
# the one place that calls systemctl directly. Found by this exact check
# printing nothing instead of "active" for a unit that really was running.
active=$(docker exec --user ts1 "$TESTER" bash -c 'export XDG_RUNTIME_DIR="/run/user/$(id -u)"; systemctl --user is-active serverjack 2>/dev/null')
result "serverjack still active after 'nothing'" "active" "$active"

echo "================================================================"
echo "(k) uninstall removes the tailscale serve mapping it owns"
reset_operator
set_ts_state ts5 running "frank@github" 0 0
run_dialogue ts5 ts5 90 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7730" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: frank@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["Run it now?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts5 exits 0" "0" "$DLG_RC"
check_serve_mapping "ts5 (before uninstall)" ts5 443 "http://127.0.0.1:7730"
out=$(docker exec --user ts5 "$TESTER" bash -c '~/.local/bin/serverjack-ctl uninstall --yes' 2>&1); rc=$?
result "ts5 uninstall exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
out=$(docker exec --user ts5 "$TESTER" bash -c 'tailscale serve status' 2>&1)
[[ $out != *"proxy http://127.0.0.1:7730"* ]] && echo "  PASS the serve mapping was removed by uninstall" \
  || { echo "  FAIL the serve mapping was removed by uninstall -- got: $out"; failures=$((failures + 1)); }

echo "================================================================"
echo "(l) a root-step prompt answered with Enter (default) must not run sudo"
reset_operator
set_ts_state ts6 running "gina@github" 0 0
run_dialogue ts6 ts6 90 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7731" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL -e PATH=/opt/fake-sudo-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: gina@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["Run it now?", ""],
 ["not yet reachable from your phone", null]]
JSON
result "ts6 exits 0 (declining the root step doesn't abort the install)" "0" "$DLG_RC"
sudo_log=$(docker exec --user ts6 "$TESTER" bash -c 'cat ~/.fake-sudo.log 2>/dev/null || true')
[[ -z $sudo_log ]] && echo "  PASS sudo was never invoked (default-Enter declined the root step)" \
  || { echo "  FAIL sudo was never invoked -- got: $sudo_log"; failures=$((failures + 1)); }
contains "explains the remaining root step instead of running it" "$(cat "$WORK/log-ts6.txt" 2>/dev/null)" "Remaining step:"

echo "================================================================"
echo "(m) rerun on (f)'s account via serverjack-ctl setup, choosing '1) update'"
# The deadlock this guards: `serverjack-ctl setup` dispatches through
# `with_lock cmd_setup`, so fd 9 is a held flock when cmd_setup execs into
# serverjack-setup. Picking "1" here makes serverjack-setup, still running
# as that same process (exec, not a subshell), invoke `serverjack-ctl
# update` as a CHILD -- which itself dispatches through `with_lock
# cmd_update` and blocks forever on a lock only this same process tree
# could ever release, while THIS process is in turn just waiting on that
# child. Nothing times out on its own; only the driver's own bounded
# timeout below turns that hang into a reported failure instead of the
# test run itself getting stuck. SERVERJACK_RELEASE_BASE_URL points update's
# own resolve step at the fake release server rather than the real GitHub
# API (so this test has no live-network dependency) -- cmd_update()
# deliberately refuses to guess "latest" on a mirror with no --version
# given ("pass --version explicitly"), which is fine here: reaching that
# refusal at all -- fast, and with an on-topic message, not the exchange
# just timing out -- is exactly what proves the child `serverjack-ctl
# update` process actually ran instead of hanging forever on the parent's
# still-held lock.
run_dialogue rerun2 ts1 30 '~/.local/bin/serverjack-ctl setup' "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["already installed here as a managed release", null],
 ["Choice [1-4, default 4]:", "1"],
 ["pass --version explicitly", null]]
JSON
result "rerun(update) completes without hanging (real response, not a deadlock)" "1" "$DLG_RC"

echo "================================================================"
echo "(n) verify_and_report survives a unit that never comes up (finding 3)"
# V2 is a deliberately broken release (bin/serverjack exits immediately, so
# the unit crash-loops and /healthz never answers). --no-serve --tcp skips
# every other prompt (tailscale, allow-list, unix/tcp), so the only thing
# this dialogue waits for is install.sh's own failure diagnostic -- which
# the OLD `active=$(... is-active ... | paste ...)` pipeline, missing
# `|| true`, would abort BEFORE ever printing (silently, under pipefail,
# the instant it saw one inactive unit) instead of reaching the health poll
# and this message.
#
# A2/A6 (this same review pass) means install.sh itself now exits 1 the
# moment its own health check fails -- serverjack-setup's own
# verify_and_report() (whose "Local health check failed" diagnostic this
# scenario originally waited for) is UNREACHABLE here now: `bash
# "$INSTALL_SH" ...` failing aborts serverjack-setup immediately under its
# own `set -e`, before verify_and_report ever runs. install.sh's own
# summary line ("did not come up healthy") is what this scenario waits for
# instead now, and it carries the SAME journalctl hint.
run_dialogue ts7 ts7 120 \
  "curl -fsSL $BASE_URL/v$V2/serverjack-bootstrap.sh | bash -s -- --no-serve --tcp --port 7695" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["did not come up healthy", null]]
JSON
result "ts7 exits 1 (health check genuinely fails, diagnostic still printed)" "1" "$DLG_RC"
contains "prints the journalctl hint" "$(cat "$WORK/log-ts7.txt" 2>/dev/null)" "journalctl --user -u serverjack -n 50"
# Finding 9's "000000" double-code bug: local_http_code() used to be
# `curl ... || echo 000` after curl's own -w already printed "000" on a
# connection failure -- two "000"s with no separator, "000000", never the
# clean "000" this checks for. Demonstrated by install.sh's own landing
# health line now (verify_and_report's equivalent message is unreachable
# in this scenario per the comment above, but it is the exact same
# local_http_code() function either way).
contains "the failed health check reports a clean HTTP 000 (finding 9), not 000000" "$(cat "$WORK/log-ts7.txt" 2>/dev/null)" "landing  http://127.0.0.1:7695/  -> HTTP 000"

echo "================================================================"
echo "(o) rerun on a git-checkout install shows the rerun menu (finding 7)"
# A real git-checkout install (bash install.sh run directly from a checkout,
# never through the bootstrap/managed-release path) -- CFG_DIR/install-path
# and a real .git DIRECTORY (not the round3 worktree's own .git, which is a
# FILE pointing elsewhere -- handle_existing_install() checks `-d
# "$repo/.git"`, so this copies the tree and gives it a plain empty .git
# dir of its own) are exactly what handle_existing_install() needs to
# recognize it as an existing install and route to rerun_git() instead of
# the old unconditional "does not migrate" refusal (exit 3).
docker exec --user ts8 "$TESTER" bash -c '
  set -e
  mkdir -p ~/checkout
  cp -a /srv/serverjack/. ~/checkout/
  rm -rf ~/checkout/.git ~/checkout/dist
  mkdir -p ~/checkout/.git
  cd ~/checkout && bash install.sh --no-serve --tcp --port 7696
' >"$WORK/log-ts8-setup.txt" 2>&1
setup_rc=$?
result "ts8: direct git-checkout install.sh exits 0" "0" "$setup_rc"
[[ $setup_rc -ne 0 ]] && sed 's/^/    | /' "$WORK/log-ts8-setup.txt"
env_before=$(docker exec --user ts8 "$TESTER" bash -c 'sha256sum ~/.config/serverjack/env' | awk '{print $1}')
run_dialogue rerung ts8 30 '~/.local/bin/serverjack-ctl setup' "" <<'JSON'
[["already installed here as a git checkout", null],
 ["Choice [1-4, default 4]:", ""],
 ["Leaving everything as it is.", null]]
JSON
result "rerun(git checkout) exits 0, shows the menu instead of refusing" "0" "$DLG_RC"
env_after=$(docker exec --user ts8 "$TESTER" bash -c 'sha256sum ~/.config/serverjack/env' | awk '{print $1}')
result "ts8: env file unchanged by 'nothing'" "$env_before" "$env_after"
active=$(docker exec --user ts8 "$TESTER" bash -c 'export XDG_RUNTIME_DIR="/run/user/$(id -u)"; systemctl --user is-active serverjack 2>/dev/null')
result "ts8: serverjack still active after the git-checkout rerun" "active" "$active"

echo "================================================================"
echo "(p) B2: rerun menu's publish on/off/port-change actually change the route"
reset_operator
set_ts_state ts9 running "ivy@github" 0 0
run_dialogue ts9 ts9 90 \
  "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --port 7760" \
  "-e SERVERJACK_RELEASE_BASE_URL=$BASE_URL" <<'JSON'
[["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: ivy@github", null],
 ["Allow only this login?", "y"],
 ["Do other people have Linux accounts on this machine?", "n"],
 ["Run it now?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts9 initial publish exits 0" "0" "$DLG_RC"
check_serve_mapping "ts9 (initial, 443)" ts9 443 "http://127.0.0.1:7760"

echo "  -- (p1) port change while staying published: the OLD port's owned"
echo "     mapping must be gone once the new one is live"
run_dialogue ts9port ts9 60 '~/.local/bin/serverjack-ctl setup --https-port 8443' "" <<'JSON'
[["already installed here as a managed release", null],
 ["Choice [1-4, default 4]:", "3"],
 ["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: ivy@github", null],
 ["Allow only this login?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts9 port change exits 0" "0" "$DLG_RC"
check_serve_mapping "ts9 (new port 8443, B2)" ts9 8443 "http://127.0.0.1:7760"
check_no_serve_mapping "ts9 (old port 443 gone after the port change, B2)" ts9 443

echo "  -- (p2) on-to-off: must remove the owned mapping, not just skip serve"
run_dialogue ts9off ts9 60 '~/.local/bin/serverjack-ctl setup' "" <<'JSON'
[["already installed here as a managed release", null],
 ["Choice [1-4, default 4]:", "3"],
 ["Tailscale is running.", null],
 ["Publish with tailscale serve", "n"],
 ["not yet reachable from your phone", null]]
JSON
result "ts9 off exits 0" "0" "$DLG_RC"
check_no_serve_mapping "ts9 off: https 8443 route actually removed (B2)" ts9 8443
[[ $(env_val ts9 SERVERJACK_ALLOW) == "ivy@github" ]] && echo "  PASS ts9 off: allow-list untouched" \
  || { echo "  FAIL ts9 off: allow-list -- got $(env_val ts9 SERVERJACK_ALLOW)"; failures=$((failures + 1)); }

echo "  -- (p3) off-to-on: the allow-list question must be asked again, not"
echo "     skipped for the local-only -> published transition"
run_dialogue ts9on ts9 60 '~/.local/bin/serverjack-ctl setup' "" <<'JSON'
[["already installed here as a managed release", null],
 ["Choice [1-4, default 4]:", "3"],
 ["Tailscale is running.", null],
 ["Publish with tailscale serve", "y"],
 ["Detected tailnet login: ivy@github", null],
 ["Allow only this login?", "y"],
 ["not yet reachable from your phone", null]]
JSON
result "ts9 off-to-on exits 0" "0" "$DLG_RC"
check_serve_mapping "ts9 (republished, 8443, B2)" ts9 8443 "http://127.0.0.1:7760"

echo "================================================================"
echo "(q) A4: setup waits for the mutation lock instead of interleaving with"
echo "    a serverjack-ctl update/rollback holding it"
# Holds ~/.local/share/serverjack/.lock in the background for 6s -- the
# SAME lock a real `serverjack-ctl update`/`rollback` takes via its own
# with_lock(). serverjack-setup's fresh-install path (step9_install_and_
# verify) must block on this (lock_acquire), not run install.sh while it's
# held.
docker exec --user ts10 "$TESTER" bash -c \
  'mkdir -p ~/.local/share/serverjack && setsid flock ~/.local/share/serverjack/.lock sleep 6 >/dev/null 2>&1 < /dev/null & disown'
start_ts=$(date +%s)
out=$(docker exec --user ts10 -e SERVERJACK_RELEASE_BASE_URL="$BASE_URL" "$TESTER" \
  bash -c "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --no-serve --tcp --port 7770" 2>&1)
rc=$?
elapsed=$(( $(date +%s) - start_ts ))
result "ts10: install still succeeds once the lock is free" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
# A FRESH install goes through the bootstrap's OWN pre-existing lock+wait
# first (bootstrap/serverjack-bootstrap.sh.in's main(), "Waiting for
# another serverjack install/update to finish...") -- it releases that
# lock right before handing off to serverjack-setup, so by the time
# THIS scenario's own hold has expired, serverjack-setup's own
# lock_acquire() (A4) usually finds it already free and never needs to
# print its own message at all. Either message proves the chain actually
# serialized against the concurrent hold rather than interleaving with it.
[[ $out == *"Waiting for another serverjack install/update to finish"* \
   || $out == *"Waiting for another serverjack-ctl/serverjack-setup run to finish"* ]] \
  && echo "  PASS ts10: printed that it was waiting for the lock" \
  || { echo "  FAIL ts10: printed that it was waiting for the lock -- got: $out"; failures=$((failures + 1)); }
if (( elapsed >= 4 )); then
  echo "  PASS ts10: actually waited for the lock (took ${elapsed}s against a 6s hold), not interleaved"
else
  echo "  FAIL ts10: took only ${elapsed}s against a 6s lock hold -- looks like it ran without waiting"
  failures=$((failures + 1))
fi

echo
if (( failures > 0 )); then
  echo "$failures guided-install check(s) failed" >&2
fi
exit $(( failures > 0 ))
