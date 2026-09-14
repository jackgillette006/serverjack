#!/usr/bin/env bash
# Regenerates docs/shots/demo.gif (and demo.mp4) from a throwaway, neutral
# serverjack instance -- never the real one on this machine, never real
# sessions or paths. Needs docker; nothing else has to be running.
#
#   bash docs/shots/make-gif.sh
#
# The fixture setup below (neutral repo copy, fake $HOME with example
# project dirs and a tiny git history, scratch SERVERJACK_CONFIG, isolated
# tmux server, three seeded sessions, serverjack + ttyd startup and health
# checks) is copied verbatim from make.sh -- read that file first if this
# needs changing, and keep the two in sync rather than letting them drift.
# This script does not depend on anything under tests/ at runtime, and it
# never touches the real serverjack units, the real tmux server, or
# ~/.config/serverjack.
#
# What's different from make.sh: instead of three static screenshots, this
# drives gif_record.py to record a Playwright video (WebKit, iPhone 14
# emulation, device_scale_factor=2) of the demo flow -- land on the
# phone-emulated landing page, pick the Claude Code pill, type
# ~/projects/3d-lab into the "...or type a path" input (the <select>
# picker never renders as a native popup under emulation, so typing is the
# only part of it that's actually visible), tap Start, sit on the live
# terminal while this script feeds the new session a short, honest,
# neutral transcript directly over tmux (see gif_record.py's docstring for
# why host-side, not live browser typing), tap back to the list -- then
# converts the recording to a GIF and an MP4 with ffmpeg in a container.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
FFIMG=jrottenberg/ffmpeg:6-alpine
REAL_REPO=$(cd ../.. && pwd)                # docs/shots -> repo root, read-only

TEST_TMP_BASE=${TMPDIR:-/tmp}
TEST_TMP_BASE=${TEST_TMP_BASE%/}
RUN_ROOT=$(mktemp -d "$TEST_TMP_BASE/serverjack-gif.XXXXXX")
chmod 700 "$RUN_ROOT"

pids=()
CID=""
cleanup() {
  [[ -n $CID ]] && docker rm -f "$CID" >/dev/null 2>&1 || true
  for p in "${pids[@]:-}"; do [[ -n $p ]] && kill "$p" 2>/dev/null || true; done
  for p in "${pids[@]:-}"; do [[ -n $p ]] && wait "$p" 2>/dev/null || true; done
  [[ -n ${TMUX_SOCK:-} ]] && tmux -S "$TMUX_SOCK" kill-server 2>/dev/null || true
  # The Playwright and ffmpeg containers run as root, so anything they wrote
  # under RUN_ROOT/out or RUN_ROOT/ff may be root-owned. Clear it from a
  # throwaway root container instead of needing sudo.
  for d in "$RUN_ROOT/out" "$RUN_ROOT/ff"; do
    if [[ -d "$d" ]]; then
      docker run --rm -v "$d":/t alpine:latest sh -c 'rm -rf /t/* /t/.[!.]* 2>/dev/null' \
        >/dev/null 2>&1 || true
    fi
  done
  case $RUN_ROOT in
    "$TEST_TMP_BASE"/serverjack-gif.*) rm -rf -- "$RUN_ROOT" ;;
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

# A fixture "claude" on PATH -- an honest stand-in, not a fake product UI.
# It just execs a plain interactive bash (reading the fake HOME's rcfiles
# set up below), so the recorded terminal shows a real, if scripted, shell
# session. Having a real `claude` executable resolvable via TOOL_PATH is
# also what makes tool_kinds() offer the "Claude Code" pill at all, and
# what the Start card's hint text ("Runs <code>") names.
FIXTURE_BIN="$RUN_ROOT/bin"
mkdir -m 700 "$FIXTURE_BIN"
cat > "$FIXTURE_BIN/claude" <<'SH'
#!/usr/bin/env bash
# Fixture stand-in for the real Claude Code CLI, used only by this
# throwaway demo instance. Honest: it just hands you a plain shell.
exec bash "$@"
SH
chmod +x "$FIXTURE_BIN/claude"
# Ahead of the real PATH so this fixture wins over any real `claude` CLI
# installed on the host running this script. This export reaches the
# server and ttyd processes (started below via `env`, which inherits the
# rest of the calling shell's environment), but NOT the tmux session
# started through the browser's Start button, below -- see the PATH line
# added to .bash_profile/.bashrc next.
export PATH="$FIXTURE_BIN:$PATH"

# A generic prompt -- no real username or hostname. \w expands relative to
# $HOME, and HOME below is this fake one, so it renders as "~" / "~/projects/game".
printf '%s\n' "PS1='dev@homeserver:\\w\$ '" "unset HISTFILE" > "$FAKE_HOME/bashrc"
printf -v session_shell 'exec env HOME=%q bash --noprofile --rcfile %q -i' \
  "$FAKE_HOME" "$FAKE_HOME/bashrc"
# Unlike the sessions started directly below (which pick their rcfile with
# --rcfile), a session started through the browser's Start button runs
# `bash -lc "<the tool's run command>"` (see command_args() in
# bin/serverjack) -- an outer *login* bash (reads ~/.bash_profile) that then
# runs the fake "Claude Code" tool's run command, which is the fixture
# `claude` wrapper above (see cfg/tools.json below), itself a nested,
# *interactive non-login* bash (reads ~/.bashrc, via Debian's patched bash
# which sources /etc/bash.bashrc first and ~/.bashrc after -- that system
# file is what was setting the real \u@\h:\w prompt here despite HOME
# already being this fake one). PS1 is a plain, unexported shell variable,
# so the outer shell's doesn't reach the inner one either way -- both files
# need it. And because it's a *login* shell, Debian's /etc/profile resets
# PATH outright before ~/.bash_profile ever runs -- wiping the PATH this
# script exported above -- so the fixture bin dir has to be re-added here
# too, or the login shell can't find the fixture `claude` on PATH at all.
# Without any of this, this session's prompt shows this machine's real
# username, hostname and /tmp checkout path, and "claude: command not
# found" instead of the fixture wrapper running.
printf '%s\n' "PS1='dev@homeserver:\\w\$ '" "unset HISTFILE" \
  "export PATH=\"$FIXTURE_BIN:\$PATH\"" \
  > "$FAKE_HOME/.bash_profile"
cp "$FAKE_HOME/.bash_profile" "$FAKE_HOME/.bashrc"

# --------------------------------------------------------------- scratch cfg
CFG="$RUN_ROOT/cfg"
mkdir -m 700 "$CFG"
cat > "$CFG/tools.json" <<'JSON'
[{"id": "claude", "label": "Claude Code", "bin": "claude", "login": "true",
  "login_check": "true", "run": "claude"}]
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

# A session started through the browser's Start button (create_session() in
# bin/serverjack) doesn't set HOME on its `tmux new-session` call, so that
# pane inherits it from the tmux SERVER's own global environment, not from
# serverjack's process env -- the fake HOME passed to serverjack below has no
# effect on it. Export it here, before the first new-session spawns the
# server, so that baseline is this fake HOME instead of the real one (which
# would otherwise leak this machine's real username, hostname and /tmp
# checkout path into the recording's prompt). The sessions created directly
# below already set HOME explicitly in their own command line and are
# unaffected either way.
export HOME="$FAKE_HOME"

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

# --------------------------------------------------------------- recording
OUT="$RUN_ROOT/out"
mkdir -p "$OUT"

CID=$(docker run -d --network host \
  -v "$PWD/gif_record.py:/w/gif_record.py:ro" -v "$OUT:/out" \
  -e SHOTS_BASE="$BASE" -e SHOTS_OUT=/out -w /w "$IMG" bash -c '
    set -euo pipefail
    pip install -q --timeout 20 --retries 1 playwright==1.62.0 >/dev/null 2>&1
    python3 gif_record.py')

# gif_record.py writes the new session name to $OUT/session_name.txt as soon
# as Start lands it on the terminal page; feed it a short, honest, neutral
# transcript over the host's own tmux (same binary/version as the server,
# unlike an apt-installed tmux inside the container) the moment we see it --
# `ls --color=always` and `git status` land almost instantly, before the
# browser has finished attaching to the terminal, so they read as a
# pre-existing session rather than something typed live; the final `ls` is
# sent the same way but is the one thing meant to look "live" in the
# recording -- then unblock the recording.
name=""
for _ in $(seq 1 100); do
  if [[ -s "$OUT/session_name.txt" ]]; then
    name=$(<"$OUT/session_name.txt")
    break
  fi
  [[ "$(docker inspect -f '{{.State.Running}}' "$CID" 2>/dev/null)" == "true" ]] || break
  sleep 0.2
done

if [[ -n $name ]]; then
  "${T[@]}" send-keys -t "$name" "ls --color=always" Enter
  sleep 0.3
  "${T[@]}" send-keys -t "$name" "git status" Enter
  sleep 0.4
  "${T[@]}" send-keys -t "$name" "ls" Enter
  : > "$OUT/typed_done"
else
  echo "warning: never got a session name from the recorder -- demo.gif will be missing the fed transcript" >&2
fi

docker wait "$CID" >/dev/null
docker logs "$CID" 2>&1 | grep -v 'GL Driver\|maybe unknown option' || true
docker rm "$CID" >/dev/null 2>&1 || true
CID=""

WEBM=$(find "$OUT" -maxdepth 1 -name '*.webm' | head -n1)
[[ -n $WEBM && -s $WEBM ]] || { echo "no video was recorded -- see above" >&2; exit 1; }

# ------------------------------------------------------------------ convert
FF="$RUN_ROOT/ff"
mkdir -p "$FF"
cp "$WEBM" "$FF/demo.webm"

# Two-pass palette (palettegen/paletteuse) gets a much cleaner GIF out of
# screen-capture-style content than a single-pass convert. Starts at
# 20fps/520px wide; if that's over the 4 MB budget, retries at 16fps, then
# 16fps/480px, before giving up.
gif_pass() {
  local fps=$1 width=$2
  docker run --rm -v "$FF:/w" "$FFIMG" -y -i /w/demo.webm \
    -vf "fps=${fps},scale=${width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
    /w/demo.gif >"$RUN_ROOT/ffmpeg-gif.log" 2>&1 || {
    echo "ffmpeg gif conversion (${fps}fps, ${width}px) failed -- see $RUN_ROOT/ffmpeg-gif.log" >&2
    tail -n 40 "$RUN_ROOT/ffmpeg-gif.log" >&2
    exit 1
  }
  echo $(( $(stat -c%s "$FF/demo.gif") / 1024 ))
}

gif_kb=$(gif_pass 20 520)
if (( gif_kb > 4096 )); then
  echo "demo.gif at 20fps/520px was ${gif_kb} KB -- retrying at 16fps/520px" >&2
  gif_kb=$(gif_pass 16 520)
fi
if (( gif_kb > 4096 )); then
  echo "demo.gif at 16fps/520px was ${gif_kb} KB -- retrying at 16fps/480px" >&2
  gif_kb=$(gif_pass 16 480)
fi
if (( gif_kb > 4096 )); then
  echo "demo.gif is still ${gif_kb} KB after dropping to 16fps/480px, over the 4 MB budget -- shorten the recording and re-run" >&2
  exit 1
fi

# The MP4 at full recording resolution (780x1688 -- iPhone 14 CSS size at
# device_scale_factor=2), for later social posts -- not linked from the
# README.
docker run --rm -v "$FF:/w" "$FFIMG" -y -i /w/demo.webm \
  -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p \
  -movflags +faststart -an /w/demo.mp4 >"$RUN_ROOT/ffmpeg-mp4.log" 2>&1 || {
  echo "ffmpeg mp4 conversion failed -- see $RUN_ROOT/ffmpeg-mp4.log" >&2
  tail -n 40 "$RUN_ROOT/ffmpeg-mp4.log" >&2
  exit 1
}

[[ -s "$FF/demo.gif" ]] || { echo "missing $FF/demo.gif -- conversion failed" >&2; exit 1; }
[[ -s "$FF/demo.mp4" ]] || { echo "missing $FF/demo.mp4 -- conversion failed" >&2; exit 1; }

cp "$FF/demo.gif" ./demo.gif
cp "$FF/demo.mp4" ./demo.mp4

echo
echo "wrote:"
echo "  $PWD/demo.gif  (${gif_kb} KB)"
echo "  $PWD/demo.mp4"
