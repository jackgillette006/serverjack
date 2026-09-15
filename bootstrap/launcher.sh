#!/usr/bin/env bash
# serverjack — thin launcher meant to be served as a physical file from
# https://jackgillette.com/serverjack/install.sh (Bluehost, no build step
# there). THIS is the canonical source (B3) -- scripts/export-launcher.sh
# copies it, byte for byte, to projects/website/serverjack/install.sh in the
# separate website repo; edit it here, never there.
#
# All it does: download the released bootstrap (bootstrap/serverjack-
# bootstrap.sh.in, rendered by scripts/build-release.sh) to a private temp
# file, sanity-check it actually looks like the whole script (not an HTML
# error page, not a truncated transfer), then exec it with this invocation's
# own arguments, stdin, stdout, stderr and exit status -- nothing more. All
# real logic (release resolution, checksum verification, the guided flow)
# belongs to the bootstrap and bin/serverjack-setup, not here.
set -Eeuo pipefail

# Test-only override (tests/launcher.sh): points at a local fixture server
# instead of the real GitHub release asset. Unset in every normal
# invocation -- same pattern as the bootstrap's own SERVERJACK_RELEASE_BASE_URL
# and bin/serverjack-setup's SERVERJACK_SETUP_TEST_OS_RELEASE.
readonly RELEASE_URL=${SERVERJACK_TEST_RELEASE_URL:-https://github.com/jackgillette006/serverjack/releases/latest/download/serverjack-bootstrap.sh}
TMP=""
# `return 0` explicitly, not just `[[ -n $TMP ]] && rm -f "$TMP"` on its
# own: that expression is FALSE (a real, nonzero exit status) whenever
# $TMP is still empty (every exit path before fetch_bootstrap ever sets it
# -- require_not_root, require_curl, check_prerequisite_floor) -- and under
# `set -e`, an EXIT trap whose own last command fails can override the
# script's actual pending exit status with the trap's, silently turning a
# deliberate `exit 2` into `exit 1`. Found by exactly that: C1's own new
# `exit 2` path came out as 1 until this was fixed.
cleanup() { [[ -n $TMP ]] && rm -f "$TMP"; return 0; }
trap cleanup EXIT

fail() {
  echo "error: $*" >&2
  echo >&2
  echo "Manual path: download and read the bootstrap yourself, then run it:" >&2
  echo "  curl -fsSLO $RELEASE_URL" >&2
  echo "  less serverjack-bootstrap.sh" >&2
  echo "  bash serverjack-bootstrap.sh" >&2
  exit 1
}

# C1. The bootstrap this launcher downloads checks the SAME floor itself
# (bootstrap/serverjack-bootstrap.sh.in's check_prerequisite_floor(), same
# logic, deliberately duplicated here rather than shared -- this script has
# to run BEFORE the bootstrap exists on disk at all) -- checking it here
# too means a machine missing something as basic as python3 fails before
# even downloading anything, with the exact install command and an offer
# to run it, rather than a wasted round-trip followed by the same failure
# one layer in.
check_prerequisite_floor() {
  local -a missing_bins=() missing_pkgs=()
  local bin pkg
  for bin in bash curl python3 tar sha256sum systemctl flock; do
    command -v "$bin" >/dev/null 2>&1 || missing_bins+=("$bin")
  done
  local have_ca=1
  if command -v dpkg >/dev/null 2>&1; then
    dpkg -s ca-certificates >/dev/null 2>&1 || have_ca=0
  elif [[ ! -e /etc/ssl/certs/ca-certificates.crt && ! -e /etc/pki/tls/certs/ca-bundle.crt ]]; then
    have_ca=0
  fi
  for bin in "${missing_bins[@]}"; do
    case "$bin" in
      bash)      pkg=bash ;;
      curl)      pkg=curl ;;
      python3)   pkg=python3 ;;
      tar)       pkg=tar ;;
      sha256sum) pkg=coreutils ;;
      systemctl) pkg=systemd ;;
      flock)     pkg=util-linux ;;
      *)         pkg=$bin ;;
    esac
    [[ " ${missing_pkgs[*]:-} " == *" $pkg "* ]] || missing_pkgs+=("$pkg")
  done
  (( have_ca )) || missing_pkgs+=(ca-certificates)
  (( ${#missing_pkgs[@]} == 0 )) && return 0

  local install_cmd
  if command -v apt-get >/dev/null 2>&1; then
    install_cmd="sudo apt-get update && sudo apt-get install -y ${missing_pkgs[*]}"
  elif command -v dnf >/dev/null 2>&1; then
    install_cmd="sudo dnf install -y ${missing_pkgs[*]}"
  else
    install_cmd="install these yourself (no apt-get or dnf found): ${missing_pkgs[*]}"
  fi
  echo "Missing prerequisites: ${missing_pkgs[*]}" >&2
  echo "  $install_cmd" >&2

  if [[ $install_cmd == sudo* ]] && { exec 8<>/dev/tty; } 2>/dev/null; then
    local reply=
    printf 'Install them now with sudo? [y/N] ' >&8
    IFS= read -r reply <&8 || reply=""
    exec 8>&-
    case "${reply,,}" in
      y|yes)
        if eval "$install_cmd"; then
          return 0
        fi
        echo "that failed -- install the missing prerequisites yourself, then re-run this." >&2
        ;;
    esac
  fi
  exit 2
}

require_not_root() {
  [ "$(id -u)" -ne 0 ] || fail "run this as your own Linux account, not root or with sudo"
}

require_curl() {
  command -v curl >/dev/null 2>&1 \
    || fail "curl is required to fetch the installer; install it first (e.g. apt install curl)"
}

# A real controlling terminal, not just a device node that happens to exist
# and be readable: `[ -r /dev/tty ]` is true even with none (the special
# file itself always "exists"; OPENING it is what fails, ENXIO, when there
# is no controlling terminal -- typical of `curl | bash` from a script/CI
# runner with no tty at all). Run in a subshell so the opened fd is closed
# again immediately either way and never leaks into run_bootstrap below.
have_tty() {
  ( exec 3<>/dev/tty ) 2>/dev/null
}

# Refuses anything that isn't plausibly the WHOLE bootstrap script: a
# Bluehost-style HTML error page (wrong URL, hosting hiccup) never starts
# with "#!/usr/bin/env bash", and a transfer cut off partway through (flaky
# connection, a proxy that truncates large responses) is caught by requiring
# the bootstrap template's own explicit end-of-file marker (see
# bootstrap/serverjack-bootstrap.sh.in) rather than assuming the download
# either fully succeeded or curl's own exit status would always say so.
verify_bootstrap() {
  local tmp=$1
  [ -s "$tmp" ] || fail "downloaded file is empty"
  head -n1 "$tmp" | grep -qx '#!/usr/bin/env bash' \
    || fail "downloaded file does not look like the bootstrap (bad first line -- got an HTML error page instead?)"
  grep -qx '# SERVERJACK-BOOTSTRAP-EOF -- do not remove: bootstrap/launcher.sh (and the' "$tmp" \
    || fail "downloaded file looks truncated (missing its end-of-file marker)"
}

# Sets TMP to the downloaded bootstrap's path. Deliberately does not return
# the path via stdout/command substitution: this function's own progress
# message ("Fetching bootstrap from: ...") used to be printed to stdout
# too, and `tmp=$(fetch_bootstrap)` captured BOTH lines into one variable --
# bash then tried to run a "path" that was actually two lines of text
# pasted together, failing with exit 127 and leaking the temp file (found
# by exactly that happening on a real PTY run). A global, not stdout, has
# no such trap; all progress output goes to stderr regardless, which is
# where it belongs in a `curl | bash` pipeline anyway.
fetch_bootstrap() {
  TMP=$(mktemp) || fail "could not create a temp file"
  echo "Fetching bootstrap from: $RELEASE_URL" >&2
  # HTTPS-only for the real download -- EXCEPT when SERVERJACK_TEST_RELEASE_URL
  # itself literally starts with "http://" (tests/launcher.sh's own local
  # fixture server; there is no real deployment where RELEASE_URL is
  # anything other than the hardcoded https:// GitHub asset above). Same
  # opt-in-only pattern the bootstrap's own fetch() and serverjack-ctl's
  # fetch() use for SERVERJACK_RELEASE_BASE_URL.
  if [[ ${SERVERJACK_TEST_RELEASE_URL:-} == http://* ]]; then
    curl -fsSL --retry 3 -o "$TMP" "$RELEASE_URL" || fail "download failed: $RELEASE_URL"
  else
    curl -fsSL --proto '=https' --tlsv1.2 --retry 3 -o "$TMP" "$RELEASE_URL" \
      || fail "download failed: $RELEASE_URL"
  fi
  verify_bootstrap "$TMP"
}

# Deliberately NOT `exec bash "$TMP" "$@"`: exec replaces this process's own
# image outright, which means the `trap cleanup EXIT` above (bound to THIS
# shell) never fires on the success path -- the temp file would be left
# behind every time the install actually works, the one case that matters
# most. Running it as an ordinary foreground child instead costs nothing
# here (there is no long-lived shell above this one relying on being
# replaced) and means EVERY exit path -- success, failure, an interrupted
# guided flow -- goes through the same cleanup.
run_bootstrap() {
  local rc
  if [ -t 0 ]; then
    bash "$TMP" "$@"; rc=$?
  elif have_tty; then
    bash "$TMP" "$@" </dev/tty; rc=$?
  else
    fail "no controlling terminal available for interactive prompts (this needs a real terminal, not another pipe or a non-interactive runner)"
  fi
  exit "$rc"
}

main() {
  require_not_root
  require_curl
  check_prerequisite_floor
  fetch_bootstrap
  run_bootstrap "$@"
}

main "$@"
