# shellcheck shell=bash
# docs/shots/fixture.sh -- the isolated, neutral serverjack instance shared by
# make.sh and make-gif.sh: a throwaway repo copy with no .git, a fake $HOME
# with example project dirs (3d-lab, game, media-stack, src) and real git
# history in two of them, the real OpenCode binary copied in (not a fake
# stand-in -- the demo opens its actual TUI) plus a scratch SERVERJACK_CONFIG,
# and an isolated tmux server with the three demo sessions already seeded.
# This is what keeps the README stills (from make.sh) and the demo GIF (from
# make-gif.sh) showing the exact same data.
#
# Sourced, not run: `source fixture.sh` from a script that has already `cd`ed
# to docs/shots, set `set -Eeuo pipefail`, and set RUN_ROOT_PREFIX (e.g.
# "serverjack-shots" or "serverjack-gif"). Declares `pids=()` itself; the
# caller's own cleanup()/trap should call fixture_cleanup (this file does not
# install a trap of its own, since a caller with extra state to clean up --
# make-gif.sh's recording container id, its ffmpeg output dir -- needs to run
# its own steps around it).
#
# Sets: RUN_ROOT, NEUTRAL_REPO, FAKE_HOME, OPENCODE_VERSION, CFG, TMUX_TMPDIR,
# TMUX_SOCK, T (a `tmux -S ...` invocation array), session_shell. Starts three
# tmux sessions (game, media-stack, 3d-lab) with game's pane already fed a
# short `ls` / `git log` transcript.
#
# Requires the real OpenCode binary to already be installed on this machine
# (checks $PATH, then ~/.opencode/bin/opencode) -- see the OpenCode section
# below. Never touches the host's own ~/.opencode or PATH: it's copied once
# into this throwaway fixture's own fake $HOME.
#
# tests/run.sh predates this file and has its own, differently-shaped fixture
# (a plain shell prompt, no OpenCode, no git history) -- it is deliberately
# left alone rather than folded in here.

: "${RUN_ROOT_PREFIX:?fixture.sh: set RUN_ROOT_PREFIX before sourcing}"

TEST_TMP_BASE=${TMPDIR:-/tmp}
TEST_TMP_BASE=${TEST_TMP_BASE%/}
RUN_ROOT=$(mktemp -d "$TEST_TMP_BASE/$RUN_ROOT_PREFIX.XXXXXX")
chmod 700 "$RUN_ROOT"

REAL_REPO=$(cd ../.. && pwd)                # docs/shots -> repo root, read-only

pids=()

fixture_cleanup() {
  local p
  for p in "${pids[@]:-}"; do [[ -n $p ]] && kill "$p" 2>/dev/null || true; done
  for p in "${pids[@]:-}"; do [[ -n $p ]] && wait "$p" 2>/dev/null || true; done
  [[ -n ${TMUX_SOCK:-} ]] && tmux -S "$TMUX_SOCK" kill-server 2>/dev/null || true
  # Playwright (and, for make-gif.sh, ffmpeg) containers run as root, so
  # anything they wrote under these dirs may be root-owned. Clear each from a
  # throwaway root container instead of needing sudo. The caller sets
  # FIXTURE_CLEAN_DIRS to whichever output dirs it actually created.
  local d
  for d in "${FIXTURE_CLEAN_DIRS[@]:-}"; do
    if [[ -n $d && -d $d ]]; then
      docker run --rm -v "$d":/t alpine:latest sh -c 'rm -rf /t/* /t/.[!.]* 2>/dev/null' \
        >/dev/null 2>&1 || true
    fi
  done
  case $RUN_ROOT in
    "$TEST_TMP_BASE/$RUN_ROOT_PREFIX".*) rm -rf -- "$RUN_ROOT" ;;
  esac
}

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

# A handful of plausible-looking files in "3d-lab" too, and its own tiny git
# history, so the recorded terminal has something real (if fake) to `ls` and
# `git status` -- neutral content, no real names or paths.
cat > "$FAKE_HOME/projects/3d-lab/render.py" <<'PY'
#!/usr/bin/env python3
"""Batch-render every scene in models/ to renders/, one PNG per frame."""
import pathlib

SCENES = sorted(pathlib.Path("models").glob("*.blend"))

def render(scene):
    print(f"rendering {scene}")

if __name__ == "__main__":
    for scene in SCENES:
        render(scene)
PY
cat > "$FAKE_HOME/projects/3d-lab/README.md" <<'MD'
# 3d-lab

Scratch space for render experiments. `models/` holds scene files,
`renders/` holds output frames. Run `render.py` to batch-render everything
in `models/`.
MD
cat > "$FAKE_HOME/projects/3d-lab/requirements.txt" <<'TXT'
numpy==2.1.1
pillow==11.0.0
TXT
: > "$FAKE_HOME/projects/3d-lab/models/scene-01.blend"
GL=(git -C "$FAKE_HOME/projects/3d-lab" -c user.name=dev -c user.email=dev@example.com
    -c commit.gpgsign=false)
"${GL[@]}" init -q
"${GL[@]}" add -A && "${GL[@]}" commit -q -m "Initial commit"
: > "$FAKE_HOME/projects/3d-lab/models/scene-02.blend"
"${GL[@]}" add -A && "${GL[@]}" commit -q -m "Add second scene"
cat >> "$FAKE_HOME/projects/3d-lab/requirements.txt" <<'TXT'
tqdm==4.66.5
TXT
"${GL[@]}" add -A && "${GL[@]}" commit -q -m "Track render progress with tqdm"
# One untracked file left sitting around, so a `git status` in the recording
# shows something rather than a flat "nothing to commit".
: > "$FAKE_HOME/projects/3d-lab/renders/frame-001.png"

# -------------------------------------------------------------- opencode --
# The real OpenCode binary, not a fake stand-in: the demo opens its actual
# TUI, so it has to be the genuine program. bin/serverjack's builtin tools
# registry already has an "opencode" entry with "paths": ["~/.opencode/bin"],
# so copying it in there is all that's needed -- no tools.json override, and
# no PATH games (command_args() resolves it through that same "paths" list,
# not a plain PATH search -- see bin/serverjack). Never touches the host's
# own ~/.opencode or PATH: this copy lives only under the fake HOME below,
# which is only ever HOME for the throwaway serverjack/ttyd processes and
# tmux sessions this file starts.
OPENCODE_SRC=$(command -v opencode || true)
[[ -n $OPENCODE_SRC ]] || OPENCODE_SRC="$HOME/.opencode/bin/opencode"
if [[ ! -x $OPENCODE_SRC ]]; then
  echo 'fixture.sh: OpenCode not found ($PATH, then ~/.opencode/bin/opencode) --' >&2
  echo "the demo needs the real program, not a fake stand-in. Install it first:" >&2
  echo "  curl -fsSL https://opencode.ai/install | bash" >&2
  exit 1
fi
mkdir -p "$FAKE_HOME/.opencode/bin"
cp "$OPENCODE_SRC" "$FAKE_HOME/.opencode/bin/opencode"
chmod +x "$FAKE_HOME/.opencode/bin/opencode"
OPENCODE_VERSION=$("$FAKE_HOME/.opencode/bin/opencode" --version 2>/dev/null || echo unknown)
echo "fixture.sh: using OpenCode $OPENCODE_VERSION from $OPENCODE_SRC" >&2

# A generic, colored prompt -- Debian's default look (bold green user@host,
# bold blue path), no real username or hostname. The \[...\] pairs wrap the
# color escapes so bash's line-wrapping math skips over them instead of
# counting them as visible columns -- without that the prompt miscounts
# itself on a resize. \w expands relative to $HOME, and HOME below is this
# fake one, so it renders as "~" / "~/projects/game".
cat > "$FAKE_HOME/bashrc" <<'RC'
PS1='\[\e[01;32m\]dev@homeserver\[\e[00m\]:\[\e[01;34m\]\w\[\e[00m\]\$ '
unset HISTFILE
RC
printf -v session_shell 'exec env HOME=%q bash --noprofile --rcfile %q -i' \
  "$FAKE_HOME" "$FAKE_HOME/bashrc"
cp "$FAKE_HOME/bashrc" "$FAKE_HOME/.bashrc"
cp "$FAKE_HOME/bashrc" "$FAKE_HOME/.bash_profile"

# --------------------------------------------------------------- scratch cfg
CFG="$RUN_ROOT/cfg"
mkdir -m 700 "$CFG"
# No tools.json needed: bin/serverjack's builtin "opencode" entry already
# points "paths" at ~/.opencode/bin, which now holds the real binary copied
# in above.
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

# A session started through the browser's Start button (create_session() in
# bin/serverjack) doesn't set HOME on its `tmux new-session` call, so that
# pane inherits it from the tmux SERVER's own global environment, not from
# serverjack's process env -- the fake HOME passed to serverjack below has no
# effect on it. Set it on the tmux session's own global environment (not a
# process-wide `export HOME=`, which would also strip docker's ~/.docker
# config for every later `docker run` this script makes -- ffmpeg and the
# recording/screenshot container both need the real HOME) as soon as a server
# exists, so that baseline is this fake HOME instead of the real one for
# every session after. A bare `set-environment -g` can't come first: tmux's
# server exits immediately once idle with no sessions and no attached
# clients, so `start-server` alone doesn't leave anything for it to talk to
# -- the first new-session has to create the server. That first session
# (like the two after it) already sets HOME explicitly on its own command
# line, so it's unaffected either way.
"${T[@]}" new-session -d -s game -x 100 -y 30 -c "$FAKE_HOME/projects/game" "$session_shell"
"${T[@]}" set-environment -g HOME "$FAKE_HOME"
"${T[@]}" new-session -d -s media-stack -x 100 -y 30 -c "$FAKE_HOME/projects/media-stack" "$session_shell"
# Looks like OpenCode is working in 3d-lab, without running anything real:
# rename this pane's own process via exec -a so tmux reports its command as
# "opencode". "exec -a" is a bash-ism (dash lacks it), so force bash
# explicitly rather than trust tmux's default-shell.
"${T[@]}" new-session -d -s 3d-lab -x 100 -y 30 -c "$FAKE_HOME/projects/3d-lab" \
  'bash -c "exec -a opencode sleep infinity"'

# Feed the "game" pane its transcript now, over tmux itself -- not by typing
# into the live xterm later. Typing through the browser raced against
# ttyd's WebSocket under load (a concurrent tests/run.sh once left the
# capture showing a blank pane): send-keys is synchronous and leaves a fixed,
# already-rendered buffer for Playwright to simply attach to and screenshot.
sleep 0.5   # let the login shell print its first prompt before send-keys
"${T[@]}" send-keys -t game "ls" Enter
sleep 0.4
"${T[@]}" send-keys -t game "git log --oneline --graph --color=always -3" Enter
sleep 0.6
