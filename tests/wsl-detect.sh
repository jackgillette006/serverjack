#!/usr/bin/env bash
# Host-side (no Docker) regression test for is_wsl() in bin/serverjack-lib.sh
# -- the helper bin/serverjack-setup's step7b_wsl_port and install.sh's
# final summary both use to warn that Windows Delivery Optimization holds
# TCP port 7680 on the WINDOWS side of a WSL2 install (see either caller's
# own comment, and is_wsl()'s own comment in serverjack-lib.sh, for the
# finding this exists for).
#
# serverjack-lib.sh is sourced directly (it has no shebang and isn't meant
# to be run on its own -- same reasoning tests/read-tailscale-self.sh and
# tests/ctl-health.sh already use for install.sh/serverjack-ctl). Each
# scenario is run in its own child `bash -c`, itself with `set -Eeuo
# pipefail` active (matching every real caller), so a false is_wsl() result
# that ever regressed into an unguarded errexit-triggering line (see
# is_wsl()'s own comment on why each of its lines is currently safe)
# would kill that child before it could print anything at all -- scenario
# (g) below checks for exactly that, past the plain true/false answers.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)

failures=0
result() {  # $1 label  $2 expected  $3 got
  if [[ $3 == "$2" ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1 -- got '$3', wanted '$2'"
    failures=$((failures + 1))
  fi
}
contains() {  # $1 label  $2 haystack  $3 needle
  if [[ $2 == *"$3"* ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1 -- expected to find: $3"
    echo "    | $2"
    failures=$((failures + 1))
  fi
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-wsl-detect-test.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# Runs is_wsl() in a fresh, real `bash -c` child (own set -e/pipefail, own
# env) and reports its exit code in $RC -- NEVER `cmd; rc=$?` at this
# script's own top level: this script has `set -Eeuo pipefail` on too, and
# a plain nonzero exit status from a standalone command (not guarded by
# if/&&/||) aborts it before `rc=$?` could ever run, the exact class of bug
# this project's own port_holder()/serve_backend_for() comments warn about.
run_is_wsl() {  # $1 SERVERJACK_TEST_OSRELEASE_FILE  $2 SERVERJACK_TEST_PROCVERSION_FILE  $3 WSL_DISTRO_NAME or ""
  RC=0
  env -u WSL_DISTRO_NAME ${3:+WSL_DISTRO_NAME="$3"} \
    SERVERJACK_TEST_OSRELEASE_FILE="$1" SERVERJACK_TEST_PROCVERSION_FILE="$2" \
    bash -c 'set -Eeuo pipefail; source "'"$REPO"'/bin/serverjack-lib.sh"; is_wsl' \
    || RC=$?
}

printf '6.12.101+deb13-amd64\n' > "$WORK/osrelease"
printf 'Linux version 6.12.101+deb13-amd64 (nobody@debian) #1 SMP\n' > "$WORK/procversion"
printf '5.15.167.4-microsoft-standard-WSL2\n' > "$WORK/osrelease-wsl2"
printf '4.4.0-19041-Microsoft\n' > "$WORK/procversion-wsl1"
printf 'MICROSOFT\n' > "$WORK/osrelease-upper"

echo "================================================================"
echo "(a) no indicator at all -- not WSL"
run_is_wsl "$WORK/osrelease" "$WORK/procversion" ""
result "(a) plain Linux is not WSL" "1" "$RC"

echo "================================================================"
echo "(b) WSL_DISTRO_NAME set (real WSL init behavior) -- WSL"
run_is_wsl "$WORK/osrelease" "$WORK/procversion" "Debian"
result "(b) WSL_DISTRO_NAME alone is enough" "0" "$RC"

echo "================================================================"
echo "(c) kernel release names microsoft (WSL2's real string) -- WSL"
run_is_wsl "$WORK/osrelease-wsl2" "$WORK/procversion" ""
result "(c) microsoft in osrelease (WSL2)" "0" "$RC"

echo "================================================================"
echo "(d) osrelease is a plain Linux one but /proc/version names Microsoft (WSL1) -- WSL"
run_is_wsl "$WORK/osrelease" "$WORK/procversion-wsl1" ""
result "(d) Microsoft in /proc/version (WSL1)" "0" "$RC"

echo "================================================================"
echo "(e) case-insensitive match"
run_is_wsl "$WORK/osrelease-upper" "$WORK/procversion" ""
result "(e) uppercase MICROSOFT still matches" "0" "$RC"

echo "================================================================"
echo "(f) the override files don't exist at all -- treated as not-WSL, no abort"
run_is_wsl "$WORK/does-not-exist-a" "$WORK/does-not-exist-b" ""
result "(f) missing override files -- not WSL, script did not abort" "1" "$RC"

echo "================================================================"
echo "(g) the real call shapes (if is_wsl; then ..., and is_wsl && ...) never"
echo "    abort a set -e/pipefail caller on a false result -- the only two"
echo "    shapes install.sh/serverjack-setup actually use"
# NOT a bare 'is_wsl' with no if/&&: that shape would trip set -e on ANY
# false predicate (a command's own nonzero exit IS what set -e watches
# for, and there is nothing a function can do about being called that
# way) -- not a real regression risk since no caller here does that. What
# IS worth proving directly is that both shapes every real caller uses
# stay exempt no matter what happens inside is_wsl(): the if-condition
# case is exempt unconditionally, and 'is_wsl && x || y' keeps is_wsl as a
# non-final list member -- if either ever broke (e.g. is_wsl regressed to
# ending on an unguarded pipeline whose exit status leaked past its own
# `return`), the child below would abort BEFORE ever reaching the marker.
marker="$WORK/still-alive"
rm -f "$marker"
env -u WSL_DISTRO_NAME SERVERJACK_TEST_OSRELEASE_FILE="$WORK/osrelease" SERVERJACK_TEST_PROCVERSION_FILE="$WORK/procversion" \
  bash -c 'set -Eeuo pipefail
source "'"$REPO"'/bin/serverjack-lib.sh"
if is_wsl; then echo wsl; else echo not-wsl; fi
is_wsl && echo yes || echo no
touch "'"$marker"'"' \
  >/dev/null 2>&1 || true
if [[ -f $marker ]]; then
  echo "  PASS (g) both real call shapes survive a false is_wsl()"
else
  echo "  FAIL (g) script aborted before the statement after a false is_wsl()"
  failures=$((failures + 1))
fi

echo "================================================================"
echo "wsl_port_note(): install.sh's final-summary WSL note"
# Runs wsl_port_note() in a fresh `bash -c` child, same reasoning as
# run_is_wsl() above -- $STDOUT/$RC end up set from it, never captured with
# a bare `cmd; rc=$?` at this script's own top level.
run_wsl_port_note() {  # $1 listen  $2 port  $3 env_file  $4 SERVERJACK_TEST_OSRELEASE_FILE  $5 WSL_DISTRO_NAME or ""
  RC=0
  STDOUT=$(env -u WSL_DISTRO_NAME ${5:+WSL_DISTRO_NAME="$5"} \
    SERVERJACK_TEST_OSRELEASE_FILE="$4" SERVERJACK_TEST_PROCVERSION_FILE="$WORK/procversion" \
    bash -c 'set -Eeuo pipefail; source "'"$REPO"'/bin/serverjack-lib.sh"; wsl_port_note "$1" "$2" "$3"' \
    _ "$1" "$2" "$3") || RC=$?
}

echo "(h) tcp + port 7680 + WSL -- note applies, names the env file and 7690"
run_wsl_port_note tcp 7680 "$HOME/.config/serverjack/env" "$WORK/osrelease-wsl2" ""
result "(h) exit 0 (note applies)" "0" "$RC"
contains "(h) mentions the reachable URL" "$STDOUT" "http://127.0.0.1:7680/"
contains "(h) says use 127.0.0.1, not localhost" "$STDOUT" "127.0.0.1, not localhost"
contains "(h) names Windows Delivery Optimization" "$STDOUT" "Windows Delivery Optimization"
contains "(h) tells the fix: SERVERJACK_PORT=7690" "$STDOUT" "SERVERJACK_PORT=7690"
contains "(h) names the actual env file path" "$STDOUT" "$HOME/.config/serverjack/env"
contains "(h) mentions --port 7690 for the one-liner" "$STDOUT" "--port 7690"

echo "(i) not WSL -- no note, nothing on stdout"
run_wsl_port_note tcp 7680 "$HOME/.config/serverjack/env" "$WORK/osrelease" ""
result "(i) exit 1 (does not apply)" "1" "$RC"
result "(i) prints nothing" "" "$STDOUT"

echo "(j) WSL, but the port already moved off 7680 -- no note (nothing left to add)"
run_wsl_port_note tcp 7690 "$HOME/.config/serverjack/env" "$WORK/osrelease-wsl2" ""
result "(j) exit 1 (already moved)" "1" "$RC"
result "(j) prints nothing" "" "$STDOUT"

echo "(k) WSL, port 7680, but unix mode -- no note (Unix sockets can't collide with DoSvc)"
run_wsl_port_note unix 7680 "$HOME/.config/serverjack/env" "$WORK/osrelease-wsl2" ""
result "(k) exit 1 (unix mode)" "1" "$RC"
result "(k) prints nothing" "" "$STDOUT"

echo "(l) WSL_DISTRO_NAME alone is enough, same as is_wsl() itself"
run_wsl_port_note tcp 7680 "$HOME/.config/serverjack/env" "$WORK/osrelease" "Debian"
result "(l) exit 0 (note applies)" "0" "$RC"
contains "(l) mentions the reachable URL" "$STDOUT" "http://127.0.0.1:7680/"

echo
if (( failures > 0 )); then
  echo "$failures WSL check(s) failed" >&2
fi
exit $(( failures > 0 ))
