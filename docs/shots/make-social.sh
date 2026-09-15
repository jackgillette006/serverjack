#!/usr/bin/env bash
# Regenerates docs/shots/social-preview.png (1280x640) by rendering
# social-preview.tmpl.html -- a small, self-contained page -- with the real
# color tokens and Prompt Jack mark pulled straight out of bin/serverjack
# (never hand-copied, so this can't drift from what actually ships) and
# screenshotting the result with Playwright in the pinned container make.sh
# and make-gif.sh use. No serverjack instance involved; this is just a
# render-and-screenshot of a static page.
#
#   bash docs/shots/make-social.sh
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
REAL_REPO=$(cd ../.. && pwd)                # docs/shots -> repo root, read-only

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

# ------------------------------------------------------------------ render
# Load bin/serverjack the same way tests/test_unit.py does (it has no .py
# suffix, so spec_from_file_location() can't guess a loader for it, and a
# scratch XDG_RUNTIME_DIR/SERVERJACK_CONFIG keep its module-level side
# effects away from anything real), pull TOKENS and PROMPT_JACK_SVG out of
# it, and fill in the template's __PLACEHOLDER__ spots with plain string
# substitution -- not str.format(), which would choke on every literal
# brace in the page's own CSS.
RENDERED="$RUN_ROOT/social-preview.html"
python3 - "$REAL_REPO/bin/serverjack" ./social-preview.tmpl.html "$RENDERED" <<'PY'
import importlib.machinery
import importlib.util
import os
import re
import sys
import tempfile

serverjack_path, tmpl_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="sj-social-runtime-")
os.environ["SERVERJACK_CONFIG"] = tempfile.mkdtemp(prefix="sj-social-config-")
for key in list(os.environ):
    if key.startswith("SERVERJACK_") and key != "SERVERJACK_CONFIG":
        del os.environ[key]

loader = importlib.machinery.SourceFileLoader("serverjack_for_social", serverjack_path)
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

tokens = dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", mod.TOKENS))

with open(tmpl_path) as f:
    html = f.read()
html = (html
        .replace("__BG_PRIMARY__", tokens["bg-primary"])
        .replace("__TEXT_PRIMARY__", tokens["text-primary"])
        .replace("__TEXT_SECONDARY__", tokens["text-secondary"])
        .replace("__ACCENT__", tokens["accent"])
        .replace("__FONT_MONO__", tokens["font-mono"])
        .replace("__FONT_UI__", tokens["font-ui"])
        .replace("__PROMPT_JACK_SVG__", mod.PROMPT_JACK_SVG))
with open(out_path, "w") as f:
    f.write(html)
print(f"rendered {out_path} from social-preview.tmpl.html + bin/serverjack's own tokens")
PY

# ------------------------------------------------------------------ shoot
OUT="$RUN_ROOT/out"
mkdir -p "$OUT"

docker run --rm \
  -v "$RENDERED:/w/social-preview.html:ro" -v "$OUT:/out" \
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
