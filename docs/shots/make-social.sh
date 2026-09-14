#!/usr/bin/env bash
# Regenerates docs/shots/social-preview.png (1280x640) by screenshotting
# social-preview.html -- a small, self-contained page using the same color
# tokens and mono font stack as the real app (see bin/serverjack's TOKENS
# block) -- with Playwright in the pinned container make.sh and
# make-gif.sh use. No serverjack instance involved; this is just a
# screenshot of a static page.
#
#   bash docs/shots/make-social.sh
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d

TEST_TMP_BASE=${TMPDIR:-/tmp}
TEST_TMP_BASE=${TEST_TMP_BASE%/}
RUN_ROOT=$(mktemp -d "$TEST_TMP_BASE/serverjack-social.XXXXXX")
chmod 700 "$RUN_ROOT"
cleanup() {
  if [[ -d "$RUN_ROOT/out" ]]; then
    docker run --rm -v "$RUN_ROOT/out":/t alpine:latest sh -c 'rm -rf /t/* /t/.[!.]* 2>/dev/null' \
      >/dev/null 2>&1 || true
  fi
  case $RUN_ROOT in
    "$TEST_TMP_BASE"/serverjack-social.*) rm -rf -- "$RUN_ROOT" ;;
  esac
}
trap cleanup EXIT

OUT="$RUN_ROOT/out"
mkdir -p "$OUT"

docker run --rm \
  -v "$PWD/social-preview.html:/w/social-preview.html:ro" -v "$OUT:/out" \
  -w /w "$IMG" bash -c '
    set -euo pipefail
    pip install -q --timeout 20 --retries 1 playwright==1.62.0 >/dev/null 2>&1
    python3 - <<PY
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={"width": 1280, "height": 640}, device_scale_factor=1).new_page()
    page.goto("file:///w/social-preview.html")
    page.wait_for_timeout(200)
    page.screenshot(path="/out/social-preview.png")
    b.close()
print("captured social-preview.png")
PY
' 2>&1 | grep -v 'GL Driver\|maybe unknown option'

[[ -s "$OUT/social-preview.png" ]] || { echo "missing $OUT/social-preview.png -- capture failed" >&2; exit 1; }
cp "$OUT/social-preview.png" ./social-preview.png

echo
echo "wrote: $PWD/social-preview.png"
