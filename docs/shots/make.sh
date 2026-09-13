#!/usr/bin/env bash
# Regenerates the three README screenshots in this directory (desktop.png,
# iphone-landing.png, iphone-term.png) from a throwaway, neutral serverjack
# instance -- never the real one on this machine, never real sessions or
# paths. Needs docker; nothing else has to be running.
#
#   bash docs/shots/make.sh
#
# Modeled on tests/run.sh's harness (read that first if this needs changing):
# an isolated tmux server (TMUX_TMPDIR), its own XDG_RUNTIME_DIR, a scratch
# SERVERJACK_CONFIG with a fake tools.json/shortcuts.json, and a Playwright
# container (mcr.microsoft.com/playwright/python) to drive real browsers.
# This script does not depend on anything under tests/ at runtime -- it only
# borrowed the pattern -- so it keeps its own copy of the pinned image and its
# own throwaway config, and it never touches the real serverjack units, the
# real tmux server, or ~/.config/serverjack.
#
# What makes the shots neutral:
#   - a fake $HOME with example project dirs (3d-lab, game, media-stack, src),
#     and sessions in them with a made-up "dev@homeserver" shell prompt
#   - bin/serverjack is run from a throwaway copy of the repo with no .git,
#     so the built-in "Update serverjack" shortcut (which names this
#     checkout's real path) never renders
#   - SERVERJACK_SSH=off, so no user@host line is computed at all
#   - one saved shortcut and one fake "Claude Code" agent (bin/login/run all
#     stubbed to `true`/`bash`, same trick tests/run.sh uses) so the
#     Shortcuts and Agents cards aren't empty, without running anything real
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
REAL_REPO=$(cd ../.. && pwd)                # docs/shots -> repo root, read-only

TEST_TMP_BASE=${TMPDIR:-/tmp}
TEST_TMP_BASE=${TEST_TMP_BASE%/}
RUN_ROOT=$(mktemp -d "$TEST_TMP_BASE/serverjack-shots.XXXXXX")
chmod 700 "$RUN_ROOT"

pids=()
cleanup() {
  for p in "${pids[@]:-}"; do [[ -n $p ]] && kill "$p" 2>/dev/null || true; done
  for p in "${pids[@]:-}"; do [[ -n $p ]] && wait "$p" 2>/dev/null || true; done
  [[ -n ${TMUX_SOCK:-} ]] && tmux -S "$TMUX_SOCK" kill-server 2>/dev/null || true
  # The Playwright container runs as root, so anything it wrote under
  # RUN_ROOT/out may be root-owned. Clear it from a throwaway root container
  # before the plain rm -rf, instead of needing sudo.
  if [[ -d "$RUN_ROOT/out" ]]; then
    docker run --rm -v "$RUN_ROOT/out":/t alpine:latest sh -c 'rm -rf /t/* /t/.[!.]* 2>/dev/null' \
      >/dev/null 2>&1 || true
  fi
  case $RUN_ROOT in
    "$TEST_TMP_BASE"/serverjack-shots.*) rm -rf -- "$RUN_ROOT" ;;
  esac
}
trap cleanup EXIT

# -------------------------------------------------------------- neutral repo
# A copy of just the three files serverjack needs to run, with no .git next
# to them -- update_available() then sees no repo to pull, so the built-in
# "Update serverjack" shortcut (which would otherwise print this checkout's
# real, non-neutral path) never appears.
NEUTRAL_REPO="$RUN_ROOT/repo"
mkdir -p "$NEUTRAL_REPO/bin"
cp "$REAL_REPO/bin/serverjack" "$REAL_REPO/bin/serverjack-ttyd" "$REAL_REPO/bin/tmux-attach.sh" \
  "$NEUTRAL_REPO/bin/"
chmod +x "$NEUTRAL_REPO"/bin/*

# ------------------------------------------------------------------ fake HOME
FAKE_HOME="$RUN_ROOT/home"
mkdir -p "$FAKE_HOME"/projects/3d-lab/{models,renders} "$FAKE_HOME"/projects/game/{src,assets} \
  "$FAKE_HOME"/projects/media-stack "$FAKE_HOME"/src
: > "$FAKE_HOME/projects/3d-lab/render.py"
: > "$FAKE_HOME/projects/game/Cargo.toml"
: > "$FAKE_HOME/projects/game/src/main.rs"
: > "$FAKE_HOME/projects/media-stack/docker-compose.yml"
# A tiny git history in "game", so the terminal shot can show a real
# `git log`. Identity is passed per command: this HOME has no global config,
# and none of this touches the real user's git configuration.
G=(git -C "$FAKE_HOME/projects/game" -c user.name=dev -c user.email=dev@example.com
   -c commit.gpgsign=false)
"${G[@]}" init -q
"${G[@]}" add -A && "${G[@]}" commit -q -m "Initial commit"
: > "$FAKE_HOME/projects/game/src/input.rs"
"${G[@]}" add -A && "${G[@]}" commit -q -m "Wire up controller input"
: > "$FAKE_HOME/projects/game/src/terrain.rs"
"${G[@]}" add -A && "${G[@]}" commit -q -m "Procedural terrain: first pass"

# A generic prompt -- no real username or hostname. \w expands relative to
# $HOME, and HOME below is this fake one, so it renders as "~" / "~/projects/game".
printf '%s\n' "PS1='dev@homeserver:\\w\$ '" "unset HISTFILE" > "$FAKE_HOME/bashrc"
printf -v session_shell 'exec env HOME=%q bash --noprofile --rcfile %q -i' \
  "$FAKE_HOME" "$FAKE_HOME/bashrc"

# --------------------------------------------------------------- scratch cfg
CFG="$RUN_ROOT/cfg"
mkdir -m 700 "$CFG"
cat > "$CFG/tools.json" <<'JSON'
[{"id": "claude", "label": "Claude Code", "bin": "true", "login": "true",
  "login_check": "true", "run": "bash"}]
JSON
cat > "$CFG/shortcuts.json" <<'JSON'
[{"id": "sc-media", "label": "Rebuild media stack",
  "cmd": "cd ~/projects/media-stack && docker compose pull && docker compose up -d"},
 {"id": "sc-snapshot", "label": "Snapshot to NAS",
  "cmd": "restic -r sftp:nas:/backups backup ~/projects"}]
JSON
chmod 600 "$CFG"/*.json

# ------------------------------------------------------------ isolated tmux
unset TMUX
export TMUX_TMPDIR="$RUN_ROOT/tmux"
mkdir -m 700 "$TMUX_TMPDIR"
# Passing -S ourselves (rather than letting a plain `tmux` build its default
# path from $TMUX_TMPDIR) means tmux won't auto-create the tmux-<uid> parent.
mkdir -m 700 "$TMUX_TMPDIR/tmux-$(id -u)"
TMUX_SOCK="$TMUX_TMPDIR/tmux-$(id -u)/default"
T=(tmux -S "$TMUX_SOCK")

"${T[@]}" new-session -d -s game -x 100 -y 30 -c "$FAKE_HOME/projects/game" "$session_shell"
"${T[@]}" new-session -d -s media-stack -x 100 -y 30 -c "$FAKE_HOME/projects/media-stack" "$session_shell"
# Looks like Claude Code is working in 3d-lab, without running anything real:
# rename this pane's own process via exec -a so tmux reports its command as
# "claude". "exec -a" is a bash-ism (dash lacks it), so force bash explicitly
# rather than trust tmux's default-shell.
"${T[@]}" new-session -d -s 3d-lab -x 100 -y 30 -c "$FAKE_HOME/projects/3d-lab" \
  'bash -c "exec -a claude sleep infinity"'

# Feed the "game" pane its transcript now, over tmux itself -- not by typing
# into the live xterm later. Typing through the browser raced against
# ttyd's WebSocket under load (a concurrent tests/run.sh once left the
# capture showing a blank pane): send-keys is synchronous and leaves a fixed,
# already-rendered buffer for Playwright to simply attach to and screenshot.
sleep 0.5   # let the login shell print its first prompt before send-keys
"${T[@]}" send-keys -t game "ls" Enter
sleep 0.4
"${T[@]}" send-keys -t game "git log --oneline -3" Enter
sleep 0.6

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

common=(SERVERJACK_LISTEN=tcp SERVERJACK_TITLE="Home server" SERVERJACK_FX=off
        SERVERJACK_CONFIG="$CFG" SERVERJACK_TOOLS=claude SERVERJACK_SSH=off
        SERVERJACK_DIRS="~/projects/3d-lab:~/projects/game:~/projects/media-stack:~/src:~"
        HOME="$FAKE_HOME" XDG_RUNTIME_DIR="$RT")
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

for f in desktop.png iphone-landing.png iphone-term.png; do
  [[ -s "$OUT/$f" ]] || { echo "missing $OUT/$f -- capture failed" >&2; exit 1; }
  cp "$OUT/$f" "./$f"
done

echo
echo "wrote:"
for f in desktop.png iphone-landing.png iphone-term.png; do
  echo "  $PWD/$f"
done
