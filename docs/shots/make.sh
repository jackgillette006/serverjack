#!/usr/bin/env bash
# Regenerates the README screenshots and logo closeups in this directory
# from a throwaway, neutral serverjack
# instance -- never the real one on this machine, never real sessions or
# paths. Needs docker; nothing else has to be running.
#
#   bash docs/shots/make.sh
#
# The fixture setup below (neutral repo copy, fake $HOME with example
# project dirs and a tiny git history, the real OpenCode binary linked in,
# scratch SERVERJACK_CONFIG, isolated tmux server, three seeded sessions)
# lives in fixture.sh, shared with make-gif.sh so the README stills and the
# demo GIF always come from the same data -- read that file first if this
# needs changing (it also requires OpenCode to already be installed on this
# machine). This script does not depend on anything under tests/ at runtime,
# and it never touches the real serverjack units, the real tmux server, or
# ~/.config/serverjack.
#
# What makes the shots neutral:
#   - a fake $HOME with example project dirs (3d-lab, game, media-stack, src),
#     and sessions in them with a made-up "dev@homeserver" shell prompt
#   - bin/serverjack is run from a throwaway copy of the repo with no .git,
#     so the built-in "Update serverjack" shortcut (which names this
#     checkout's real path) never renders
#   - SERVERJACK_SSH=off, so no user@host line is computed at all
#   - one saved shortcut and the real OpenCode binary (see fixture.sh -- not
#     a fake stand-in) so the Shortcuts and Agents cards aren't empty
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d

RUN_ROOT_PREFIX=serverjack-shots
source ./fixture.sh

FIXTURE_CLEAN_DIRS=()
cleanup() {
  FIXTURE_CLEAN_DIRS=("$RUN_ROOT/out")
  fixture_cleanup
}
trap cleanup EXIT

# --------------------------------------------------------------- serverjack
RT="$RUN_ROOT/rt"
mkdir -m 700 "$RT"
PORT=$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)
BASE="http://127.0.0.1:$PORT"

# $FAKE_HOME/.opencode/bin is prepended so the fixture's own OpenCode is what
# a bare `opencode` resolves to, even on a machine whose ambient PATH (which
# bin/serverjack's TOOL_PATH searches before a tool's own "paths" entries --
# see fixture.sh's OpenCode section) already has a real one on it.
common=(SERVERJACK_LISTEN=tcp SERVERJACK_TITLE="Home server" SERVERJACK_FX=off
        SERVERJACK_CONFIG="$CFG" SERVERJACK_TOOLS=opencode SERVERJACK_SSH=off
        SERVERJACK_DIRS="~/projects/3d-lab:~/projects/game:~/projects/media-stack:~/src:~"
        HOME="$FAKE_HOME" XDG_RUNTIME_DIR="$RT" PATH="$FAKE_HOME/.opencode/bin:$PATH")
env "${common[@]}" SERVERJACK_PORT="$PORT" \
  python3 "$NEUTRAL_REPO/bin/serverjack" >"$RUN_ROOT/web.log" 2>&1 & pids+=($!)
env "${common[@]}" \
  bash "$NEUTRAL_REPO/bin/serverjack-ttyd" >"$RUN_ROOT/ttyd.log" 2>&1 & pids+=($!)

for _ in $(seq 1 50); do curl -sf -o /dev/null "$BASE/healthz" && break; sleep 0.2; done
curl -sf -o /dev/null "$BASE/healthz" || {
  echo "serverjack never came up -- see $RUN_ROOT/web.log" >&2
  tail -n 40 "$RUN_ROOT/web.log" >&2 || true
  exit 1
}
curl -sf -o /dev/null "$BASE/term/" || {
  echo "ttyd never came up behind serverjack -- see $RUN_ROOT/ttyd.log" >&2
  tail -n 40 "$RUN_ROOT/ttyd.log" >&2 || true
  exit 1
}

# ------------------------------------------------------------------ capture
OUT="$RUN_ROOT/out"
mkdir -p "$OUT"
docker run --rm --network host -v "$PWD/shots.py:/w/shots.py:ro" -v "$OUT:/out" \
  -e SHOTS_BASE="$BASE" -e SHOTS_OUT=/out -w /w "$IMG" bash -c '
    set -euo pipefail
    pip install -q --timeout 15 --retries 1 playwright==1.62.0 >/dev/null 2>&1
    python3 shots.py' 2>&1 | grep -v 'GL Driver\|maybe unknown option'

for f in desktop.png iphone-landing.png iphone-term.png dir-search.png prompt-jack-header.png prompt-jack-icon.png; do
  [[ -s "$OUT/$f" ]] || { echo "missing $OUT/$f -- capture failed" >&2; exit 1; }
  cp "$OUT/$f" "./$f"
done

echo
echo "wrote:"
for f in desktop.png iphone-landing.png iphone-term.png dir-search.png prompt-jack-header.png prompt-jack-icon.png; do
  echo "  $PWD/$f"
done
