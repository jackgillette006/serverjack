#!/usr/bin/env bash
# Builds a release archive from the current working tree and renders the
# bootstrap script for it. Run this from the checkout at the commit/tag being
# released -- it packages whatever is on disk right now, it does not fetch
# anything.
#
# Usage: scripts/build-release.sh <version>     (e.g. 1.4.0, no leading "v")
#
# Produces:
#   dist/serverjack-<version>.tar.gz   the release archive
#   dist/serverjack-bootstrap.sh       rendered from bootstrap/serverjack-bootstrap.sh.in,
#                                       with this archive's download URL and
#                                       sha256 embedded (skipped with a notice
#                                       if the template is missing)
#   dist/SHA256SUMS                    sha256 of every file dist/ ships
#
# .github/workflows/release.yml runs this on a pushed tag and attaches all
# three to a draft GitHub release. See CONTRIBUTING.md "Releasing".
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
REPO=$PWD

version=${1:?usage: scripts/build-release.sh <version>}
[[ $# -eq 1 ]] || { echo "usage: scripts/build-release.sh <version>" >&2; exit 1; }
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]] \
  || { echo "version must look like X.Y.Z (got: $version)" >&2; exit 1; }

# Single source of truth: bin/serverjack's own VERSION constant. Refusing a
# mismatch here is what stops a release archive from shipping a binary that
# reports a different version than the tag it was published under.
current=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' bin/serverjack)
[[ -n $current ]] || { echo "could not find VERSION in bin/serverjack" >&2; exit 1; }
[[ $current == "$version" ]] || {
  echo "bin/serverjack VERSION is $current, not $version -- bump it first (see CONTRIBUTING.md Releasing)" >&2
  exit 1
}

for c in tar sha256sum git; do
  command -v "$c" >/dev/null 2>&1 || { echo "missing: $c" >&2; exit 1; }
done

for f in bin systemd install.sh uninstall.sh LICENSE README.md CHANGELOG.md docs/FAQ.md; do
  [[ -e $f ]] || { echo "missing required release file: $f" >&2; exit 1; }
done

DIST=$REPO/dist
rm -rf "$DIST"
mkdir -p "$DIST"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
name="serverjack-$version"
pkg="$stage/$name"
mkdir -p "$pkg/docs"

cp -a bin "$pkg/bin"
cp -a systemd "$pkg/systemd"
cp install.sh uninstall.sh LICENSE README.md CHANGELOG.md "$pkg/"
cp docs/FAQ.md "$pkg/docs/FAQ.md"

# A dev checkout accumulates things a release archive should not ship.
find "$pkg" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$pkg" -name '*.pyc' -delete

sha=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)
build_date=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > "$pkg/RELEASE" <<EOF
version=$version
git_sha=$sha
build_date=$build_date
EOF

# Deterministic archive: fixed mtime, numeric owner, sorted entries -- two
# builds from the same tree (RELEASE's build_date aside, which is
# deliberately real) produce byte-identical tarballs.
archive="$DIST/$name.tar.gz"
tar --sort=name --mtime="$build_date" --owner=0 --group=0 --numeric-owner \
    -C "$stage" -czf "$archive" "$name"

(cd "$DIST" && sha256sum "$(basename "$archive")" > SHA256SUMS)

template=$REPO/bootstrap/serverjack-bootstrap.sh.in
if [[ -f $template ]]; then
  archive_sha=$(sha256sum "$archive" | awk '{print $1}')
  url="https://github.com/jackgillette006/serverjack/releases/download/v$version/$name.tar.gz"
  sed -e "s|@VERSION@|$version|g" \
      -e "s|@ARCHIVE_URL@|$url|g" \
      -e "s|@ARCHIVE_SHA256@|$archive_sha|g" \
      "$template" > "$DIST/serverjack-bootstrap.sh"
  chmod 755 "$DIST/serverjack-bootstrap.sh"
  (cd "$DIST" && sha256sum serverjack-bootstrap.sh >> SHA256SUMS)
  echo "built $DIST/serverjack-bootstrap.sh"
else
  echo "note: $template not found -- skipped rendering the bootstrap" >&2
fi

echo "built $archive"
echo "built $DIST/SHA256SUMS"
