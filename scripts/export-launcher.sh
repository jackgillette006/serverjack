#!/usr/bin/env bash
# Exports bootstrap/launcher.sh (the canonical launcher source, B3) to the
# website repo as serverjack/install.sh, byte for byte plus one header
# banner recording where it came from. This script only WRITES a file --
# it never touches SFTP, git, or anything live; deploying it to
# jackgillette.com is a separate, deliberate step in the website repo's own
# workflow (see projects/website/CLAUDE.md), never automatic here.
#
# Usage:
#   bash scripts/export-launcher.sh <path-to-website-repo>
#   e.g. bash scripts/export-launcher.sh ~/workspace/projects/website
#
# Writes <repo>/serverjack/install.sh and <repo>/serverjack/SOURCE.txt
# (recording this commit's sha and the export time), refusing to run unless
# <repo>/serverjack/ already exists (this script creates a file, not a
# website layout).
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
REPO=$PWD

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}
[[ ${1:-} != -h && ${1:-} != --help ]] || usage 0
website_repo=${1:?usage: scripts/export-launcher.sh <path-to-website-repo>}
[[ $# -eq 1 ]] || { echo "usage: scripts/export-launcher.sh <path-to-website-repo>" >&2; exit 1; }

target_dir="$website_repo/serverjack"
[[ -d $target_dir ]] \
  || { echo "$target_dir does not exist -- pass the website repo's root, not the serverjack/ subdirectory itself" >&2; exit 1; }

launcher="$REPO/bootstrap/launcher.sh"
[[ -f $launcher ]] || { echo "internal error: $launcher not found" >&2; exit 1; }

sha=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

target="$target_dir/install.sh"
{
  head -n1 "$launcher"
  cat <<EOF
# Exported byte-for-byte from bootstrap/launcher.sh in the serverjack repo
# (commit $sha, exported $now) by scripts/export-launcher.sh.
# EDIT THE SOURCE, NOT THIS FILE: bootstrap/launcher.sh in the serverjack
# repo is canonical; this copy exists only because Bluehost cannot run a
# build step. Re-run scripts/export-launcher.sh after changing it there.
EOF
  tail -n +2 "$launcher"
} > "$target"
chmod 755 "$target"

cat > "$target_dir/SOURCE.txt" <<EOF
serverjack commit: $sha
launcher exported: $now
EOF

echo "wrote $target"
echo "wrote $target_dir/SOURCE.txt"
echo "Review the diff, then commit/preview/deploy in the website repo's own workflow (see projects/website/CLAUDE.md) -- this script does not do that itself."
