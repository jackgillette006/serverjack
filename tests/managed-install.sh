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
#       while a tmux session with a running command survives, replaying the
#       --no-serve flag persisted from the original bootstrap (a fake
#       tailscale on PATH proves it is never invoked)
#   (d) updating to a THIRD, deliberately broken release (its bin/serverjack
#       exits 1) is refused and auto-rolled-back; the prior version answers
#       200 again, and so does the PREVIOUS release's own serverjack-ctl (the
#       broken release's install.sh already overwrote it before the health
#       check ran)
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
#   (k) a no-op `update` (already-current version) never touches the live
#       release directory "current" resolves to
#   (l) a bootstrap run whose install.sh fails once (a deliberately flaky
#       release) is completed by a second, identical `curl | bash`
#   (m) `serverjack-ctl update` still succeeds with SERVERJACK_ALLOW set (the
#       health check must not probe /term/, which 403s under ALLOW)
#   (n) install.sh refuses when run directly (not via serverjack-ctl) from a
#       release directory "current" does not point at
#   (o) `serverjack-ctl update` also refuses, and leaks no temp archive,
#       against the same corrupted release used in (h)
#   (p) uninstall.sh refuses when run directly (not via serverjack-ctl) from
#       inside a managed release directory
#   (q) a git-checkout install with "%" and a space in its path is still
#       correctly detected as channel=git, not misparsed via ExecStart=
#   (r) `serverjack-ctl status` survives one unit being stopped
#   (s) fetch() (bootstrap and serverjack-ctl) keeps the HTTPS pin unless
#       SERVERJACK_RELEASE_BASE_URL literally starts with "http://" -- an
#       https:// mirror never has --proto-redir dropped
#   (t) `serverjack-ctl update` interrupted (SIGINT) mid-activation leaves
#       install.json already correct (written before the swap, not only
#       after success), and rollback afterward still works
#   (u) a dangling "current" (uninstall.sh unreachable): `uninstall --yes`
#       still removes the units via the fallback, and reports it
#   (v) a unit that genuinely can't be removed: `uninstall --yes` exits
#       non-zero and leaves $SHARE in place, rather than reporting success
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

# --------------------------------------------------- fetch() proto pin (s)
# Host-side, no docker needed: extracts each fetch() function verbatim from
# its source file and calls it with a fake `curl` that just echoes its argv,
# so we can see directly whether --proto/--proto-redir made it through for a
# given SERVERJACK_RELEASE_BASE_URL. This is the exact mechanism that used
# to be wrong (finding: "drops the pin for ANY value, including https
# mirrors") -- an https:// mirror that 302s a download down to plain http is
# what --proto-redir refuses; dropping it silently follows the downgrade.
echo "== (s) fetch() keeps the HTTPS pin unless SERVERJACK_RELEASE_BASE_URL literally starts with http://"
check_fetch_pin() {  # $1 label, $2 file, $3 SERVERJACK_RELEASE_BASE_URL value, $4 expect "pinned"|"unpinned"
  local label=$1 file=$2 base_url=$3 expect=$4
  local fn; fn=$(sed -n '/^fetch() {/,/^}/p' "$file")
  local argv got=unpinned
  argv=$(SERVERJACK_RELEASE_BASE_URL="$base_url" bash -c "
curl() { printf '%s\n' \"\$@\"; }
$fn
fetch -o /dev/null http://example.invalid/x
")
  [[ $argv == *"--proto-redir"* ]] && got=pinned
  result "$label" "$expect" "$got"
}
for f in ctl:bin/serverjack-ctl bootstrap:bootstrap/serverjack-bootstrap.sh.in; do
  label=${f%%:*}; path=${f#*:}
  check_fetch_pin "$label fetch(): SERVERJACK_RELEASE_BASE_URL unset -> pinned" "$REPO/$path" "" pinned
  check_fetch_pin "$label fetch(): a real http:// mirror -> unpinned (the documented opt-in)" "$REPO/$path" "http://mirror.example/x" unpinned
  check_fetch_pin "$label fetch(): an https:// mirror -> STILL pinned (the bug: used to drop it for ANY set value)" "$REPO/$path" "https://mirror.example/x" pinned
  check_fetch_pin "$label fetch(): a scheme-less mirror -> pinned (doesn't literally start with http://)" "$REPO/$path" "mirror.example/x" pinned
done

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
# exits 1 immediately, and bin/serverjack-ctl carries a marker comment) --
# proves auto-rollback restores the PREVIOUS release's units/env AND its
# serverjack-ctl (finding 7), not just the former. V4 = another good bump
# whose SERVED archive gets one byte flipped after building -- its bootstrap
# still carries the correct pinned sha256, so the mismatch is what must be
# caught. V5 = a "flaky" release whose install.sh fails on its first run and
# succeeds on a second, identical one -- proves a bootstrap install that
# fails partway is resumable with a second `curl | bash` (finding 3). V6 =
# a "slow" release whose install.sh sleeps for a while right at the start
# (after touching a marker file) -- gives a real `serverjack-ctl update` a
# wide, reliable window to interrupt with SIGINT mid-flight (second-review
# finding 1: an interrupt between the pre-swap install.json write and the
# health-confirmed finalize must leave a resumable, rollback-able record).
V1=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$REPO/bin/serverjack")
V2="9.9.9-test"
V3="9.9.10-broken-test"
V4="9.9.6-corrupt-test"
V5="9.9.7-resume-test"
V6="9.9.3-slow-test"
[[ -n $V1 ]] || { echo "could not read VERSION from bin/serverjack" >&2; exit 1; }
V3_CTL_MARKER="SJMI_TEST_MARKER_V3_CTL"
V6_SLOW_MARKER="/tmp/sjmi-slow-marker"

WEBROOT="$WORK/webroot"
mkdir -p "$WEBROOT/v$V1" "$WEBROOT/v$V2" "$WEBROOT/v$V3" "$WEBROOT/v$V4" "$WEBROOT/v$V5" \
  "$WEBROOT/v$V6" "$WEBROOT/trunc" "$WEBROOT/tools"

build_variant() {  # $1 version  $2 dir-to-copy-from  $3 mode: real|bump|broken|flaky|slow
  local version=$1 src=$2 mode=$3
  local vdir="$WORK/src-$version"
  cp -a "$src" "$vdir"
  rm -rf "$vdir/.git" "$vdir/dist"
  if [[ $mode != real ]]; then
    sed -i "s/^VERSION = \".*\"/VERSION = \"$version\"/" "$vdir/bin/serverjack"
  fi
  if [[ $mode == broken ]]; then
    sed -i '1i import sys; sys.exit(1)  # deliberately broken -- tests/managed-install.sh' "$vdir/bin/serverjack"
    # A distinguishing, otherwise-inert marker in THIS release's
    # serverjack-ctl -- (d) below asserts it does NOT end up installed after
    # the auto-rollback, proving restore_from_backup() puts back the
    # previous (good) release's serverjack-ctl, not just its units/env.
    echo "# $V3_CTL_MARKER" >> "$vdir/bin/serverjack-ctl"
  fi
  if [[ $mode == flaky ]]; then
    # Fails install.sh's very first real line (right after `set -euo
    # pipefail`, before it touches anything durable -- no ttyd/fzf fetch,
    # no units) and succeeds on any rerun, via a marker file on the host
    # running it. Proves finding 3: a failed managed install must be
    # resumable with a second curl|bash, not stuck half-installed forever.
    python3 - "$vdir/install.sh" "/tmp/sjmi-flaky-$version-marker" <<'PY'
import sys

path, marker = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    lines = fh.readlines()
inject = (
    'MARKER="%s"\n'
    '[[ -f "$MARKER" ]] || { touch "$MARKER"; '
    'echo "deliberately failing this run -- tests/managed-install.sh finding 3" >&2; exit 1; }\n'
) % marker
for i, line in enumerate(lines):
    if line.strip() == "set -euo pipefail":
        lines.insert(i + 1, inject)
        break
else:
    raise SystemExit("could not find insertion point in install.sh")
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(lines)
PY
  fi
  if [[ $mode == slow ]]; then
    # Touches a marker (so the test can wait for "definitely inside the
    # sleep now" instead of racing a fixed delay) then sleeps well past any
    # reasonable time-to-interrupt, every run -- unlike "flaky" this never
    # fails or speeds up; the test kills it from outside.
    python3 - "$vdir/install.sh" "$V6_SLOW_MARKER" <<'PY'
import sys

path, marker = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    lines = fh.readlines()
inject = 'touch "%s"; sleep 25\n' % marker
for i, line in enumerate(lines):
    if line.strip() == "set -euo pipefail":
        lines.insert(i + 1, inject)
        break
else:
    raise SystemExit("could not find insertion point in install.sh")
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(lines)
PY
  fi
  ( cd "$vdir" && bash scripts/build-release.sh "$version" ) >/tmp/"$RUNID"-build.log 2>&1 \
    || { echo "build_variant $version failed:" >&2; cat /tmp/"$RUNID"-build.log >&2; exit 1; }
  rm -f /tmp/"$RUNID"-build.log
  cp "$vdir/dist/serverjack-$version.tar.gz" "$vdir/dist/serverjack-bootstrap.sh" "$vdir/dist/SHA256SUMS" \
    "$WEBROOT/v$version/"
}

say "Building test releases V1=$V1 (real) V2=$V2 (bump) V3=$V3 (broken) V4=$V4 (to be corrupted) V5=$V5 (flaky) V6=$V6 (slow)"
build_variant "$V1" "$REPO" real
build_variant "$V2" "$REPO" bump
build_variant "$V3" "$REPO" broken
build_variant "$V4" "$REPO" bump
build_variant "$V5" "$REPO" flaky
build_variant "$V6" "$REPO" slow

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
# A fixed "halfway through the file" byte count is fragile: it used to land
# mid-function, but growing any function earlier in the file (as fixing a
# review finding did) shifts halfway past the LAST function's closing brace,
# landing on a syntactively complete file that legitimately exits 0 -- same
# as head2000.sh, proving nothing new. Anchor on main() itself instead: it is
# the last, and by far the longest, function in the file, so a cut shortly
# after its opening "{" is always deep inside an unterminated function body
# no matter how much earlier functions grow.
main_off=$(grep -bo '^main() {$' "$WEBROOT/v$V1/serverjack-bootstrap.sh" | head -1 | cut -d: -f1)
[[ -n $main_off ]] || { echo "could not find main() in serverjack-bootstrap.sh to anchor the mid-function cut" >&2; exit 1; }
head -c "$((main_off + 60))" \
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
# tester3: a fresh account for the resumable-install (finding 3) and
# SERVERJACK_ALLOW (finding 1) scenarios, kept separate from tester/tester2
# so those don't have to interleave with an unrelated install/version
# sequence.
docker exec "$TESTER" useradd -m -s /bin/bash tester3
# tester4: dedicated to the uninstall/partial-removal scenarios (finding 3)
# so a dangling "current" or a permission-blocked unit dir doesn't leave
# tester/tester2/tester3 in a weird state for whatever runs after them.
docker exec "$TESTER" useradd -m -s /bin/bash tester4
docker exec "$TESTER" loginctl enable-linger tester
docker exec "$TESTER" loginctl enable-linger tester2
docker exec "$TESTER" loginctl enable-linger tester3
docker exec "$TESTER" loginctl enable-linger tester4
for u in tester tester2 tester3 tester4; do
  for _ in $(seq 1 30); do
    docker exec "$TESTER" test -S "/run/user/$(docker exec "$TESTER" id -u "$u")/bus" 2>/dev/null && break
    sleep 0.5
  done
done

# Cache each user's uid once -- looking it up per call (docker exec id -u)
# works but is needless overhead across the ~50+ calls below.
TESTER_UID=$(docker exec "$TESTER" id -u tester)
TESTER2_UID=$(docker exec "$TESTER" id -u tester2)
TESTER3_UID=$(docker exec "$TESTER" id -u tester3)
TESTER4_UID=$(docker exec "$TESTER" id -u tester4)
run_as() {  # $1 = user ("tester".."tester4"), remaining args = one command string
  local user=$1 uid; shift
  case "$user" in
    tester2) uid=$TESTER2_UID ;;
    tester3) uid=$TESTER3_UID ;;
    tester4) uid=$TESTER4_UID ;;
    *)       uid=$TESTER_UID ;;
  esac
  docker exec --user "$user" -e XDG_RUNTIME_DIR="/run/user/$uid" \
    -e SERVERJACK_RELEASE_BASE_URL="$BASE_URL" -e PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin" \
    -w /tmp "$TESTER" bash -c "$*"
}

# A fake `tailscale` on the container's PATH, ahead of nothing (there is no
# real one in this image) -- logs every invocation and otherwise behaves
# well enough for install.sh's own checks to proceed as if tailscale were up
# (`tailscale status`, `tailscale serve status`, `tailscale status --json`).
# Every managed install in this file uses --no-serve or (for updates)
# relies on that flag being persisted (finding 4) EXCEPT where a scenario
# below deliberately checks this log, so its being empty at that point is
# itself part of what proves the fix.
FAKE_TAILSCALE_LOG=/tmp/fake-tailscale.log
cat > "$WORK/fake-tailscale" <<'SH'
#!/bin/sh
echo "$*" >> /tmp/fake-tailscale.log
case "$1" in
  status)
    if [ "$2" = "--json" ]; then
      echo '{"Self":{"DNSName":"faketailnet.example.ts.net."}}'
    fi
    exit 0 ;;
  *) exit 0 ;;
esac
SH
chmod 755 "$WORK/fake-tailscale"
docker cp "$WORK/fake-tailscale" "$TESTER:/usr/local/bin/tailscale"
docker exec "$TESTER" touch "$FAKE_TAILSCALE_LOG"
docker exec "$TESTER" chmod 666 "$FAKE_TAILSCALE_LOG"

# From here on, a command failing is a test RESULT, not a script bug -- every
# scenario below expects at least one command to fail on purpose (root
# refusal, the broken release, the no-tty prompt, a truncated or corrupted
# download). -u and pipefail stay on; only -e (abort on the first nonzero)
# has to go, or the very first such check would kill the whole test run
# before recording anything.
set +e

echo "== ttyd/fzf provisioning (host-side setup)"
provision_ttyd_fzf() {  # $1 = user
  local user=$1 out
  out=$(run_as "$user" "mkdir -p ~/.local/bin \
    && curl -fsSL $BASE_URL/tools/ttyd -o ~/.local/bin/ttyd \
    && curl -fsSL $BASE_URL/tools/fzf -o ~/.local/bin/fzf \
    && chmod 755 ~/.local/bin/ttyd ~/.local/bin/fzf" 2>&1)
  if [[ $? -eq 0 ]]; then
    echo "  PASS pre-fetched ttyd/fzf installed into $user's ~/.local/bin"
  else
    echo "  FAIL pre-fetched ttyd/fzf installed into $user's ~/.local/bin"
    echo "$out" | sed 's/^/    | /'
    failures=$((failures + 1))
  fi
}
provision_ttyd_fzf tester
# tester3 needs a real, successful install too (the resumable-install and
# SERVERJACK_ALLOW scenarios below both end with a genuinely running
# release, not just a refused/truncated attempt).
provision_ttyd_fzf tester3
# tester4: the uninstall/partial-removal scenarios need real, running
# installs (twice -- one gets fully uninstalled, a second one tests partial
# removal), so it needs ttyd/fzf too.
provision_ttyd_fzf tester4

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

# ------------------------------------------------ (k) no-op update, live dir
# A sentinel file inside the LIVE release directory: tar extraction only
# ever creates files that are actually in the archive, so this file
# surviving proves the directory itself was never rm -rf'd -- a same-hash
# re-extraction (the archive is byte-identical) could not be told apart
# from "never touched" any other way.
echo "== (k) a no-op update (already current) never touches the live release directory"
run_as tester "touch ~/.local/share/serverjack/releases/$V1/.sjmi-sentinel"
out=$(run_as tester "~/.local/bin/serverjack-ctl update --version $V1 --yes" 2>&1); rc=$?
result "no-op update exits 0" "0" "$rc"
[[ $out == *"already current"* ]] && echo "  PASS says serverjack $V1 is already current" \
  || { echo "  FAIL says serverjack $V1 is already current -- got: $out"; failures=$((failures + 1)); }
sentinel=$(run_as tester "test -f ~/.local/share/serverjack/releases/$V1/.sjmi-sentinel && echo yes || echo no")
result "live release directory was never removed by the no-op update" "yes" "$sentinel"
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz still 200 after the no-op update" "200" "$code"

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
# V1 was installed with --no-serve (a). That is a run-time-only install.sh
# flag with nothing in the env file to remember it by -- clearing the fake
# tailscale log first and asserting no `tailscale serve ...` call shows up
# in it after this update is what proves --no-serve was replayed (finding
# 4): if it weren't, install.sh's serve section would run, calling
# `tailscale status` (this stub answers "up"), then `tailscale serve
# status`/`--bg ...`, all starting with "serve" and logged here. (bin/
# serverjack itself calls plain `tailscale status --json` on every startup,
# --no-serve or not, to learn its own tailnet hostname -- that's expected
# and unrelated, which is why this checks for "serve" specifically rather
# than requiring the log to be empty.)
run_as tester "> $FAKE_TAILSCALE_LOG"
out=$(run_as tester "~/.local/bin/serverjack-ctl update --version $V2 --yes" 2>&1); rc=$?
result "update to V2 exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version is V2 after update" "$V2" "$code"
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after update" "200" "$code"
alive=$(run_as tester "tmux has-session -t survivor 2>/dev/null && echo yes || echo no")
result "tmux session survived the update" "yes" "$alive"
tsc=$(run_as tester "grep -c '^serve' $FAKE_TAILSCALE_LOG || true")
result "--no-serve (persisted from bootstrap) meant \`tailscale serve\` was never invoked by the update" "0" "$tsc"

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
# V3's install.sh already overwrote ~/.local/bin/serverjack-ctl with its own
# (marked) copy before the health check even ran. restore_from_backup()
# must put back V2's serverjack-ctl too, not just the units/env -- finding 7.
marker=$(run_as tester "grep -c $V3_CTL_MARKER ~/.local/bin/serverjack-ctl || true")
result "serverjack-ctl itself was restored to the pre-update (V2) copy, not V3's" "0" "$marker"

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

# ------------------------------------------- (n) install.sh direct-run guard
# V2's release directory is still staged (nothing prunes it) but "current"
# points at V1 again after (f) -- running V2's install.sh BY HAND (no
# SERVERJACK_CTL_MANAGED) must refuse rather than silently bake "current"
# (which resolves to V1, not V2) into the units.
echo "== (n) install.sh refuses when run directly from a release dir \"current\" does not point at"
out=$(run_as tester "bash ~/.local/share/serverjack/releases/$V2/install.sh --no-serve" 2>&1); rc=$?
result "direct install.sh from a non-current release exits 1" "1" "$rc"
[[ $out == *"serverjack-ctl update"* ]] && echo "  PASS points at serverjack-ctl update" \
  || { echo "  FAIL points at serverjack-ctl update -- got: $out"; failures=$((failures + 1)); }
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version unaffected by the refused direct install.sh" "$V1" "$code"

# --------------------------------------- (o) ctl-side corrupted archive leak
# The same corrupted V4 archive (h) uses below, but through serverjack-ctl's
# OWN stage_release() this time, not the bootstrap's download_and_verify() --
# proves the temp-dir leak fix (finding 10) and the "stage into a temp dir,
# never touch the target until verified" rewrite (finding 2) on the
# serverjack-ctl side too, not just the bootstrap's.
echo "== (o) serverjack-ctl update also refuses a corrupted archive, and leaks nothing"
out=$(run_as tester "~/.local/bin/serverjack-ctl update --version $V4 --yes" 2>&1); rc=$?
[[ $rc -ne 0 ]] && echo "  PASS ctl update to the corrupted release exits non-zero" \
  || { echo "  FAIL ctl update to the corrupted release exits non-zero -- got 0"; failures=$((failures + 1)); }
[[ $out == *"checksum mismatch"* ]] && echo "  PASS output names a checksum mismatch" \
  || { echo "  FAIL output names a checksum mismatch -- got: $out"; failures=$((failures + 1)); }
code=$(run_as tester "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version unchanged (still V1) after the refused ctl update" "$V1" "$code"
staged=$(run_as tester "test -d ~/.local/share/serverjack/releases/$V4 && echo yes || echo no")
result "no half-staged release directory for the corrupted version" "no" "$staged"
leftover=$(run_as tester "find /tmp -maxdepth 4 -name 'serverjack-*.tar.gz' 2>/dev/null | wc -l")
result "no leftover serverjack-*.tar.gz under /tmp after ctl's corrupted-archive attempt" "0" "$leftover"

# ---------------------------------------- (p) uninstall.sh direct-run guard
echo "== (p) uninstall.sh refuses when run directly, not via serverjack-ctl"
out=$(run_as tester "bash ~/.local/share/serverjack/current/uninstall.sh" 2>&1); rc=$?
result "direct uninstall.sh exits 1" "1" "$rc"
[[ $out == *"serverjack-ctl uninstall"* ]] && echo "  PASS points at serverjack-ctl uninstall" \
  || { echo "  FAIL points at serverjack-ctl uninstall -- got: $out"; failures=$((failures + 1)); }
code=$(run_as tester "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "units untouched by the refused direct uninstall (/healthz still 200)" "200" "$code"

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

# --------------------------------------------------- (q) git channel, % path
# tester2 has no managed install at this point (both attempts above were
# refused), so it's a free account to fabricate a git-checkout install on:
# a fake checkout directory (a ".git" dir is all detect_channel() checks for)
# whose path contains "%" and a space -- exactly what used to come back
# broken when detect_channel() parsed and un-escaped ExecStart= instead of
# reading the plain-text install-path file install.sh now writes.
echo "== (q) git-checkout channel detection survives a path with \"%\" and a space"
# Reuses V1's already-served archive rather than `docker cp` (one less way
# for this to depend on the host docker client/daemon behaving a particular
# way) to get a real serverjack-ctl onto tester2 without a full install.
GITREPO='/tmp/repo 100% done'
setup_out=$(run_as tester2 "mkdir -p ~/.local/bin && curl -fsSL $BASE_URL/v$V1/serverjack-$V1.tar.gz -o /tmp/sjmi-v1-for-q.tar.gz \
  && tar -xzf /tmp/sjmi-v1-for-q.tar.gz -O serverjack-$V1/bin/serverjack-ctl > ~/.local/bin/serverjack-ctl \
  && chmod 755 ~/.local/bin/serverjack-ctl && ls -la ~/.local/bin/serverjack-ctl" 2>&1); setup_rc=$?
if [[ $setup_rc -ne 0 ]]; then
  echo "  FAIL could not stage a serverjack-ctl copy onto tester2 for this scenario -- got: $setup_out"
  failures=$((failures + 1))
fi
# A minimal bin/serverjack with a VERSION line, the way a real checkout
# would have one -- also exercises cmd_status's git branch reading it back.
run_as tester2 "mkdir -p '$GITREPO/.git' '$GITREPO/bin' ~/.config/serverjack \
  && printf '%s\n' '$GITREPO' > ~/.config/serverjack/install-path \
  && printf 'VERSION = \"9.9.5-fake-git\"\n' > '$GITREPO/bin/serverjack'"
out=$(run_as tester2 "~/.local/bin/serverjack-ctl status" 2>&1)
[[ $out == *"channel:  git checkout ($GITREPO)"* ]] && echo "  PASS reports channel=git with the \"%\"/space path intact" \
  || { echo "  FAIL reports channel=git with the \"%\"/space path intact -- got: $out (setup: $setup_out)"; failures=$((failures + 1)); }
[[ $out == *"current:  9.9.5-fake-git"* ]] && echo "  PASS also reads the version back out of that checkout" \
  || { echo "  FAIL also reads the version back out of that checkout -- got: $out"; failures=$((failures + 1)); }

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

# --------------------------------------------- (l) resumable failed install
# V5's install.sh fails its very first real line on a run whose marker file
# doesn't exist yet, and succeeds once it does (see build_variant mode
# "flaky" above). The first curl|bash here is expected to fail; the second,
# identical one must complete the install -- finding 3.
echo "== (l) a failed install.sh run is completed by a second, identical curl|bash"
out=$(run_as tester3 "curl -fsSL $BASE_URL/v$V5/serverjack-bootstrap.sh | bash -s -- --no-serve" 2>&1); rc=$?
[[ $rc -ne 0 ]] && echo "  PASS the first (deliberately flaky) run fails" \
  || { echo "  FAIL the first (deliberately flaky) run fails -- exited 0"; failures=$((failures + 1)); }
state=$(run_as tester3 "grep -c '\"installing\"' ~/.local/share/serverjack/install.json 2>/dev/null || true")
result "install.json was staged with state=installing after the failed first run" "1" "$state"
code=$(run_as tester3 "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz 2>/dev/null")
[[ $code != 200 ]] && echo "  PASS nothing is actually running yet after the failed run (got $code)" \
  || { echo "  FAIL nothing is actually running yet after the failed run -- got 200"; failures=$((failures + 1)); }
out=$(run_as tester3 "curl -fsSL $BASE_URL/v$V5/serverjack-bootstrap.sh | bash -s -- --no-serve" 2>&1); rc=$?
result "the second, identical run exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester3 "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after the resumed install" "200" "$code"
code=$(run_as tester3 "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "serverjack-ctl status reports V5 after resuming" "$V5" "$code"
state=$(run_as tester3 "grep -c '\"installing\"' ~/.local/share/serverjack/install.json 2>/dev/null || true")
result "install.json's state=installing marker was cleared by the successful install.sh" "0" "$state"

# ------------------------------------------- (m) update survives ALLOW=alice
# Continuing on tester3 (now on V5): enable SERVERJACK_ALLOW and restart, then
# prove /term/ (unauthenticated) is refused -- the exact mechanism that broke
# wait_healthy()'s old /term/ probe -- and that `serverjack-ctl update` still
# succeeds anyway, because health no longer depends on that probe (finding 1).
echo "== (m) serverjack-ctl update still succeeds with SERVERJACK_ALLOW set"
run_as tester3 "sed -i 's/^#SERVERJACK_ALLOW=/SERVERJACK_ALLOW=alice@example.com/' ~/.config/serverjack/env"
run_as tester3 "systemctl --user restart serverjack serverjack-ttyd"
# The restart itself is synchronous but the freshly-started process still
# needs a moment to bind its socket -- give it a few retries rather than one
# immediate probe (every other scenario's health check gets this for free
# via wait_healthy()'s own 30s loop; this one is a raw curl instead so it
# can also probe /term/, which wait_healthy() deliberately does not).
code=$(run_as tester3 "c=000; for i in \$(seq 1 20); do c=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz); [ \"\$c\" = 200 ] && break; sleep 0.5; done; echo \"\$c\"")
result "/healthz still 200 once SERVERJACK_ALLOW is set (always open)" "200" "$code"
code=$(run_as tester3 "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/term/")
result "/term/ is 403 for a plain loopback request once SERVERJACK_ALLOW is set (the old health probe's failure mode)" "403" "$code"
out=$(run_as tester3 "~/.local/bin/serverjack-ctl update --version $V2 --yes" 2>&1); rc=$?
result "update exits 0 even though SERVERJACK_ALLOW is set" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester3 "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version is V2 after the update" "$V2" "$code"
code=$(run_as tester3 "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after the update" "200" "$code"

# ------------------------------------------- (r) status survives a stopped unit
# `systemctl --user is-active a b` exits non-zero whenever EITHER unit isn't
# active -- under pipefail that used to abort `status` entirely with no
# output at all (finding 6), which is exactly the situation someone runs
# `status` to look at (right after a stop or a crash), not a script bug.
echo "== (r) serverjack-ctl status survives one unit being stopped"
run_as tester3 "systemctl --user stop serverjack-ttyd"
out=$(run_as tester3 "~/.local/bin/serverjack-ctl status" 2>&1); rc=$?
result "status exits 0 even with one unit stopped" "0" "$rc"
[[ $out == *"units:"* && $out == *"serverjack-ttyd=inactive"* ]] && echo "  PASS full status output printed, showing serverjack-ttyd inactive" \
  || { echo "  FAIL full status output printed, showing serverjack-ttyd inactive -- got: $out"; failures=$((failures + 1)); }
run_as tester3 "systemctl --user start serverjack-ttyd" >/dev/null

# ------------------- (t) an interrupted update: resumable, rollback works
# V6's install.sh touches a marker file then sleeps 25s right at the start
# -- a wide, reliable window to land a real SIGINT mid-activation. Launched
# detached (docker exec -d) so the test can send it a signal from outside;
# `echo $$ > pidfile; exec serverjack-ctl ...` records the PID of the
# exec'd serverjack-ctl process itself (exec replaces the image, keeps the
# pid), not some wrapper shell around it.
echo "== (t) an interrupted update leaves a resumable, rollback-able record"
UPDATE_PID_FILE=/tmp/sjmi-update-pid
run_as tester3 "rm -f $V6_SLOW_MARKER $UPDATE_PID_FILE"
docker exec -d --user tester3 -e XDG_RUNTIME_DIR="/run/user/$TESTER3_UID" \
  -e SERVERJACK_RELEASE_BASE_URL="$BASE_URL" -e PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin" \
  -w /tmp "$TESTER" bash -c \
  "echo \$\$ > $UPDATE_PID_FILE; exec ~/.local/bin/serverjack-ctl update --version $V6 --yes > /tmp/sjmi-update.log 2>&1"

marker_seen=0
for _ in $(seq 1 30); do
  run_as tester3 "test -f $V6_SLOW_MARKER" && { marker_seen=1; break; }
  sleep 1
done
[[ $marker_seen -eq 1 ]] && echo "  PASS install.sh's injected sleep started (definitely mid-activation now)" \
  || { echo "  FAIL install.sh's injected sleep started -- timed out waiting for the marker file"; failures=$((failures + 1)); }

# The core of finding 1: install.json must ALREADY be correct at this point
# -- written before the swap, not only after a successful health check.
ij=$(run_as tester3 "cat ~/.local/share/serverjack/install.json" 2>/dev/null)
[[ $ij == *'"state": "activating"'* ]] && echo "  PASS install.json already shows state=activating (written before the swap, not after)" \
  || { echo "  FAIL install.json already shows state=activating -- got: $ij"; failures=$((failures + 1)); }
[[ $ij == *"\"version\": \"$V6\""* ]] && echo "  PASS ...naming the new version" \
  || { echo "  FAIL ...naming the new version -- got: $ij"; failures=$((failures + 1)); }
[[ $ij == *"\"previous\": \"$V2\""* ]] && echo "  PASS ...and the CORRECT previous version (not stale/desynced)" \
  || { echo "  FAIL ...and the correct previous version -- got: $ij"; failures=$((failures + 1)); }
cur=$(run_as tester3 "readlink ~/.local/share/serverjack/current")
result "\"current\" already points at the new release" "releases/$V6" "$cur"

# Signal the PROCESS GROUP, not just the recorded pid: bash blocked in a
# synchronous wait() for a foreground child (here, install.sh, itself
# blocked on its own `sleep`) does not act on a caught signal promptly --
# empirically confirmed it waits for the child to finish first, only then
# runs the trap. That's just an artifact of signaling a single pid, though:
# a real Ctrl-C in a terminal (or a session-ending SIGHUP, or a reboot's
# signal to the whole unit) hits the WHOLE foreground process group at
# once, which also kills the child directly and unblocks the parent's
# wait() immediately -- confirmed empirically too. `docker exec -d` gives
# the launched process its own session, so its pgid equals its own pid.
run_as tester3 "kill -INT -\$(cat $UPDATE_PID_FILE) 2>/dev/null; true"
dead=0
for _ in $(seq 1 15); do
  run_as tester3 "kill -0 \$(cat $UPDATE_PID_FILE) 2>/dev/null" || { dead=1; break; }
  sleep 1
done
[[ $dead -eq 1 ]] && echo "  PASS the update process actually died after SIGINT" \
  || { echo "  FAIL the update process actually died after SIGINT"; failures=$((failures + 1)); }
log=$(run_as tester3 "cat /tmp/sjmi-update.log" 2>/dev/null)
[[ $log == *"interrupted while activating"* ]] && echo "  PASS the interrupt trap printed its diagnostic" \
  || echo "  (note: interrupt trap message not seen in the log -- not fatal, install.json is the real proof) -- got: $log"

# The property that actually matters: rollback (or another update) must
# work correctly afterward, not refuse or misreport -- this is what the OLD
# write-after-swap ordering broke (status showed the old version with
# previous=null, and rollback refused with nothing to roll back to).
out=$(run_as tester3 "~/.local/bin/serverjack-ctl rollback --yes" 2>&1); rc=$?
result "rollback after the interrupt exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
code=$(run_as tester3 "~/.local/bin/serverjack-ctl status | sed -n 's/^current:  //p'")
result "current version is back to V2 after the post-interrupt rollback" "$V2" "$code"
code=$(run_as tester3 "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7680/healthz")
result "/healthz is 200 after the post-interrupt rollback" "200" "$code"
ij2=$(run_as tester3 "cat ~/.local/share/serverjack/install.json" 2>/dev/null)
[[ $ij2 != *'"state"'* ]] && echo "  PASS install.json's activating marker is gone after a clean rollback" \
  || { echo "  FAIL install.json's activating marker is gone after a clean rollback -- got: $ij2"; failures=$((failures + 1)); }

# --------------------------------- (u) dangling current, uninstall --yes
# $CURRENT/uninstall.sh is unreachable through a dangling symlink (its
# release directory gone) -- the OLD code had NOTHING that removed the
# units in this case (just a warning, then rm -rf $SHARE, still reporting
# "removed: units..." and exit 0 while the units kept running). The fix's
# fallback (remove_units_and_serve_route()) doesn't depend on $CURRENT at
# all, so it must still get the units down and report accurately.
# tester/tester2/tester3 and tester4 are separate Linux accounts but share
# ONE network namespace (the container's) -- unlike separate machines, they
# are NOT isolated from each other's ports. tester3 stays up and running
# (SERVERJACK_PORT default 7680) for the rest of this file after scenario
# (t), so tester4 needs its own port or install.sh's own port-clash check
# correctly refuses it (found by exactly that happening here). --port also
# sidesteps needing a fake/blocked tailscale serve setup for these two.
TESTER4_PORT=7690
bootstrap_install_retry() {  # $1 = user
  local user=$1 out rc n
  for n in 1 2 3; do
    out=$(run_as "$user" "curl -fsSL $BASE_URL/v$V1/serverjack-bootstrap.sh | bash -s -- --no-serve --port $TESTER4_PORT" 2>&1); rc=$?
    (( rc == 0 )) && { printf '%s' "$out"; return 0; }
    echo "  (fresh install for $user failed, retrying: $n/3)" >&2
    sleep 2
  done
  printf '%s' "$out"
  return "$rc"
}

echo "== (u) dangling \"current\": uninstall --yes still removes the units"
out=$(bootstrap_install_retry tester4); rc=$?
result "tester4: fresh install for (u) exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
run_as tester4 "ln -sfn releases/does-not-exist ~/.local/share/serverjack/current"
out=$(run_as tester4 "~/.local/bin/serverjack-ctl uninstall --yes" 2>&1); rc=$?
result "uninstall --yes with a dangling current exits 0 (fallback fully succeeded)" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
[[ $out == *"removing the units and serve route directly"* ]] && echo "  PASS output says it used the fallback (uninstall.sh was unreachable)" \
  || { echo "  FAIL output says it used the fallback -- got: $out"; failures=$((failures + 1)); }
unit_gone=$(run_as tester4 "systemctl --user list-unit-files serverjack.service serverjack-ttyd.service 2>/dev/null | grep -c '\\.service' || true")
result "both unit files are actually gone (not just \$SHARE)" "0" "$unit_gone"
share_gone=$(run_as tester4 "test -d ~/.local/share/serverjack && echo present || echo gone")
result "\$SHARE removed (the fallback fully succeeded)" "gone" "$share_gone"

# ------------------ (v) partial removal: exit non-zero, $SHARE preserved
# A second, fresh install -- this time the unit directory itself is made
# unwritable (owner's own write bit removed) so `rm -f` on the unit files
# genuinely fails (a directory needs write+execute to remove entries from
# it; being the file's owner isn't enough). The fallback must detect that
# and refuse to call it done: no $SHARE removal, non-zero exit.
echo "== (v) a unit that could not be removed: exit non-zero, \$SHARE kept"
out=$(bootstrap_install_retry tester4); rc=$?
result "tester4: fresh install for (v) exits 0" "0" "$rc"
[[ $rc -ne 0 ]] && echo "$out" | sed 's/^/    | /'
run_as tester4 "ln -sfn releases/does-not-exist ~/.local/share/serverjack/current"
run_as tester4 "chmod 500 ~/.config/systemd/user"
out=$(run_as tester4 "~/.local/bin/serverjack-ctl uninstall --yes" 2>&1); rc=$?
[[ $rc -ne 0 ]] && echo "  PASS uninstall exits non-zero when a unit could not actually be removed" \
  || { echo "  FAIL uninstall exits non-zero when a unit could not actually be removed -- got 0"; failures=$((failures + 1)); }
[[ $out == *"could not be fully removed"* ]] && echo "  PASS output says removal was incomplete, not \"removed\"" \
  || { echo "  FAIL output says removal was incomplete -- got: $out"; failures=$((failures + 1)); }
run_as tester4 "chmod 700 ~/.config/systemd/user"
still_there=$(run_as tester4 "systemctl --user list-unit-files serverjack.service serverjack-ttyd.service 2>/dev/null | grep -c '\\.service' || true")
[[ $still_there -gt 0 ]] && echo "  PASS at least one unit file is still there (removal genuinely failed, not just misreported)" \
  || { echo "  FAIL at least one unit file is still there -- got count: $still_there"; failures=$((failures + 1)); }
share_kept=$(run_as tester4 "test -d ~/.local/share/serverjack && echo present || echo gone")
result "\$SHARE was NOT removed when removal was incomplete" "present" "$share_kept"
# Clean up so this doesn't count as a leaked/broken install for anything
# that might run after it -- best effort, this is the last use of tester4.
run_as tester4 "~/.local/bin/serverjack-ctl uninstall --yes" >/dev/null 2>&1 || true

echo
if (( failures > 0 )); then
  echo "$failures managed-install check(s) failed" >&2
fi
exit $(( failures > 0 ))
