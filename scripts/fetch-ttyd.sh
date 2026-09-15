#!/usr/bin/env bash
# Fetches, verifies and installs the ttyd release binary this project pins,
# to the path given as $1. Shared by install.sh (real installs) and
# .github/workflows/ci.yml, so both use the exact same ttyd -- the version
# and its per-arch sha256 live in exactly one place, here.
#
# That sharing matters for real: CI used to `apt-get install ttyd`.
# ubuntu-24.04's archive carries 1.7.4, and that client does not apply a
# `?theme=...` URL query at all -- a real bug (the terminal silently
# falling back to ttyd's stock theme on an older client) passed CI clean
# against that mismatched version and only showed up once CI ran the same
# ttyd a real install actually gets.
#
# Usage: scripts/fetch-ttyd.sh <output-path>
set -euo pipefail

TTYD_VER=1.7.7
# sha256 of every asset, copied from ttyd's own published SHA256SUMS. Pinned
# HERE on purpose: fetching the checksum file from the same host as the
# binary proves only that the two agree, so whoever can swap one can swap
# the other. A mismatch means the release was re-cut or something is wrong
# -- check before bumping this.
declare -A SHA256=(
  [ttyd.x86_64]=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
  [ttyd.aarch64]=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
  [ttyd.armhf]=8240c8438b68d3b10b0e1a4e7c914d70fca6a7606b516f40bf40adfa1044d801
)

out=${1:?"usage: fetch-ttyd.sh <output-path>"}

arch=$(uname -m)
case "$arch" in
  x86_64)  asset=ttyd.x86_64 ;;
  aarch64) asset=ttyd.aarch64 ;;
  armv7l)  asset=ttyd.armhf ;;
  *) echo "fetch-ttyd.sh: unsupported arch $arch -- install ttyd $TTYD_VER yourself at $out" >&2; exit 1 ;;
esac

if "$out" --version 2>/dev/null | grep -q "$TTYD_VER"; then
  echo "fetch-ttyd.sh: $out is already ttyd $TTYD_VER" >&2
  exit 0
fi

# Every download here: HTTPS only, and no redirect may leave it.
fetch() { curl -fsSL --proto '=https' --proto-redir '=https' "$@"; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
base=https://github.com/tsl0922/ttyd/releases/download/$TTYD_VER
fetch -o "$tmp/$asset" "$base/$asset"

want=${SHA256[$asset]:-}
[[ -n $want ]] || { echo "fetch-ttyd.sh: no pinned sha256 for $asset -- refusing to install it" >&2; exit 1; }
echo "$want  $asset" | (cd "$tmp" && sha256sum -c - >/dev/null) || {
  echo "fetch-ttyd.sh: $asset does not match the sha256 pinned in this script -- refusing to install it" >&2
  exit 1
}
# Belt and braces: also check against the project's own checksum file, best
# effort -- a network hiccup fetching it is not a reason to refuse a binary
# that already matched the pinned hash above.
if fetch -o "$tmp/sums.$$" "$base/SHA256SUMS" 2>/dev/null; then
  grep -q "^$want  $asset\$" "$tmp/sums.$$" \
    || echo "fetch-ttyd.sh: note: $asset matches the pinned hash but not $base/SHA256SUMS (upstream re-cut a release?)" >&2
fi

mkdir -p "$(dirname "$out")"
install -m 755 "$tmp/$asset" "$out"
echo "fetch-ttyd.sh: installed ttyd $TTYD_VER -> $out" >&2
