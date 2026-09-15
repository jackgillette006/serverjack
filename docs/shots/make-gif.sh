#!/usr/bin/env bash
# Regenerates docs/shots/demo.gif (and demo.mp4) from a throwaway, neutral
# serverjack instance -- never the real one on this machine, never real
# sessions or paths. Needs docker; nothing else has to be running.
#
#   bash docs/shots/make-gif.sh
#
# The fixture setup (neutral repo copy, fake $HOME with example project dirs
# and a tiny git history, the real OpenCode binary linked in, scratch
# SERVERJACK_CONFIG, isolated tmux server, three seeded sessions,
# serverjack + ttyd startup and health checks) lives in fixture.sh, shared
# with make.sh so the README stills and this GIF always come from the same
# data -- read that file first if this needs changing (it also requires
# OpenCode to already be installed on this machine, and fails loudly if it
# isn't -- this GIF is meant to show the real program, never a fake one).
# This script does not depend on anything under tests/ at runtime, and it
# never touches the real serverjack units, the real tmux server, or
# ~/.config/serverjack.
#
# What's different from make.sh: instead of three static screenshots, this
# drives gif_record.py to record a Playwright video (WebKit, iPhone 14
# emulation, device_scale_factor=2) of the demo flow -- land on the
# phone-emulated landing page, pick the OpenCode pill, type
# ~/projects/3d-lab into the "...or type a path" input (the <select>
# picker never renders as a native popup under emulation, so typing is the
# only part of it that's actually visible), tap Start, sit on the live
# terminal while the real OpenCode TUI opens in that directory (see
# gif_record.py's docstring), tap back to the list -- then converts the
# recording to a GIF and an MP4 with ffmpeg in a container.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d
FFIMG=jrottenberg/ffmpeg:6-alpine

RUN_ROOT_PREFIX=serverjack-gif
source ./fixture.sh

CID=""
FIXTURE_CLEAN_DIRS=()
cleanup() {
  [[ -n $CID ]] && docker rm -f "$CID" >/dev/null 2>&1 || true
  FIXTURE_CLEAN_DIRS=("$RUN_ROOT/out" "$RUN_ROOT/ff")
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
# screenReaderMode=true mirrors the terminal's text into a real DOM tree
# (.xterm-accessibility-tree) purely so gif_record.py can wait for OpenCode's
# actual "Ask anything" ready text instead of a fixed sleep -- xterm.js
# renders to canvas by default, so that text isn't otherwise in the DOM.
env "${common[@]}" TTYD_EXTRA_ARGS='-t screenReaderMode=true' \
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
# as Start lands it on the terminal page -- read it just so the regression
# check below knows which tmux session to look at. Nothing is fed into this
# pane over tmux any more: its foreground process is the real OpenCode TUI
# (not a shell), so send-keys here would type raw characters into its chat
# input instead of running a command. gif_record.py itself just waits for
# the TUI to render and holds on it.
name=""
for _ in $(seq 1 100); do
  if [[ -s "$OUT/session_name.txt" ]]; then
    name=$(<"$OUT/session_name.txt")
    break
  fi
  [[ "$(docker inspect -f '{{.State.Running}}' "$CID" 2>/dev/null)" == "true" ]] || break
  sleep 0.2
done

# Fail hard rather than silently writing a blank-capture demo.gif over the
# real one: a missing session name means Start never actually landed on the
# terminal, so nothing below would show anything worth recording.
if [[ -z $name ]]; then
  echo "error: never got a session name from the recorder -- demo.gif would be a blank capture" >&2
  echo "-- recorder container log --" >&2
  docker logs "$CID" 2>&1 | grep -v 'GL Driver\|maybe unknown option' >&2 || true
  exit 1
fi

# Same readiness check as gif_record.py's, from the host side via tmux
# instead of the browser: OpenCode's "Ask anything" ready text must actually
# be on screen before either check below trusts what the pane shows. Plain
# capture-pane (no -a) reads whatever is *currently displayed* -- OpenCode's
# own alternate-screen TUI once it's running -- which is what this needs;
# it's the -a form below, not this one, that reaches behind it into the
# shell's own screen and scrollback.
ready=0
for _ in $(seq 1 100); do
  if "${T[@]}" capture-pane -p -t "=$name:" | grep -q 'Ask anything'; then
    ready=1
    break
  fi
  sleep 0.2
done
if [[ $ready -ne 1 ]]; then
  echo "error: OpenCode's \"Ask anything\" ready text never appeared in the pane" >&2
  echo "-- last capture --" >&2
  "${T[@]}" capture-pane -p -t "=$name:" >&2 || true
  exit 1
fi

# Regression check for command_args() in bin/serverjack: the recorded pane's
# echoed "$ <cmd>" line (printed just before OpenCode's TUI takes over the
# screen, so it's only reachable now via -a, which reads the shell's own
# screen and scrollback instead of OpenCode's current alternate screen) must
# show the plain configured command ("opencode"), never a resolved
# TOOL_PATH location -- that would bake this throwaway run's own /tmp path
# into a public asset (the demo GIF). Fail loudly rather than ship a GIF
# that leaks it.
pane_text=$("${T[@]}" capture-pane -p -J -a -t "=$name:")
if grep -q '/tmp/' <<<"$pane_text"; then
  echo "error: the recorded pane shows a /tmp/ path -- command_args() must leave the" >&2
  echo "configured command text untouched (see bin/serverjack)" >&2
  echo "$pane_text" | tail -n 20 >&2
  exit 1
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

# ------------------------------------------------------- letterbox check --
# gif_record.py's record_video_size must exactly match the emulated
# viewport in CSS px times its device_scale_factor, or Playwright pads the
# recording out to it with a flat grey band (this happened for real: the
# size was hardcoded against a stale assumption about the iPhone 14
# viewport). Don't just trust the math by eye -- sample the last frame's
# bottom 10% of rows against its top 10%: the app's own background is
# near-black everywhere (landing page and terminal alike), so a materially
# lighter bottom band means letterboxing got through.
read -r VIDEO_W VIDEO_H < <(
  docker run --rm -v "$FF:/w" "$FFIMG" -i /w/demo.webm >"$RUN_ROOT/ffprobe.log" 2>&1 || true
  grep -oP 'Video:.*?\K\d+x\d+' "$RUN_ROOT/ffprobe.log" | head -n1 | tr x ' '
)
if [[ -z ${VIDEO_W:-} || -z ${VIDEO_H:-} ]]; then
  echo "couldn't read demo.webm's resolution -- see $RUN_ROOT/ffprobe.log" >&2
  exit 1
fi

check_letterbox() {   # sets LETTERBOXED=yes/no from the current demo.webm
  docker run --rm -v "$FF:/w" "$FFIMG" -y -sseof -0.3 -i /w/demo.webm \
    -frames:v 1 -f rawvideo -pix_fmt gray /w/lastframe.gray \
    >"$RUN_ROOT/ffmpeg-frame.log" 2>&1 || {
    echo "couldn't grab the last frame for the letterbox check -- see $RUN_ROOT/ffmpeg-frame.log" >&2
    exit 1
  }
  LETTERBOXED=$(python3 - "$FF/lastframe.gray" "$VIDEO_W" "$VIDEO_H" <<'PY'
import sys
path, w, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with open(path, "rb") as f:
    data = f.read()
band = max(1, h // 10)
def mean(r0, r1):
    chunk = data[r0 * w:r1 * w]
    return sum(chunk) / len(chunk) if chunk else 0.0
top, bottom = mean(0, band), mean(h - band, h)
# A flat grey pad reads dramatically brighter than this app's near-black
# background; 40 (of 255) is well above any real UI content down there.
print(f"yes {top:.1f} {bottom:.1f}" if bottom - top > 40 else f"no {top:.1f} {bottom:.1f}")
PY
)
}

check_letterbox
read -r verdict top_mean bottom_mean <<<"$LETTERBOXED"
if [[ $verdict == yes ]]; then
  echo "demo.webm is letterboxed (top rows avg ${top_mean}, bottom rows avg ${bottom_mean}) -- detecting a crop" >&2
  docker run --rm -v "$FF:/w" "$FFIMG" -i /w/demo.webm -vf cropdetect=24:2:0 -frames:v 60 -f null - \
    >"$RUN_ROOT/ffmpeg-cropdetect.log" 2>&1 || true
  CROP=$(grep -oP 'crop=\K\S+' "$RUN_ROOT/ffmpeg-cropdetect.log" | tail -n1)
  [[ -n $CROP ]] || {
    echo "letterboxing detected but cropdetect found nothing to crop -- see $RUN_ROOT/ffmpeg-cropdetect.log" >&2
    exit 1
  }
  docker run --rm -v "$FF:/w" "$FFIMG" -y -i /w/demo.webm -vf "crop=$CROP" -c:v libvpx-vp9 -an \
    /w/demo-cropped.webm >"$RUN_ROOT/ffmpeg-crop.log" 2>&1 || {
    echo "ffmpeg crop re-encode ($CROP) failed -- see $RUN_ROOT/ffmpeg-crop.log" >&2
    exit 1
  }
  mv "$FF/demo-cropped.webm" "$FF/demo.webm"
  check_letterbox
  read -r verdict top_mean bottom_mean <<<"$LETTERBOXED"
  if [[ $verdict == yes ]]; then
    echo "still letterboxed after cropping to $CROP (top ${top_mean}, bottom ${bottom_mean}) -- giving up" >&2
    exit 1
  fi
  echo "cropped to $CROP -- top ${top_mean}, bottom ${bottom_mean}" >&2
fi

# Two-pass palette (palettegen/paletteuse) gets a much cleaner GIF out of
# screen-capture-style content than a single-pass convert. gif_pass() only
# runs ffmpeg and reports success/failure; the size check and the
# 20fps/520px -> 16fps/520px -> 16fps/480px retry ladder both live in the
# loop below, in plain sight rather than folded into the function's return
# value.
gif_pass() {
  local fps=$1 width=$2
  docker run --rm -v "$FF:/w" "$FFIMG" -y -i /w/demo.webm \
    -vf "fps=${fps},scale=${width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
    /w/demo.gif >"$RUN_ROOT/ffmpeg-gif.log" 2>&1
}

FPS_RUNGS=(20 16 16)
WIDTH_RUNGS=(520 520 480)
gif_kb=0
fit=0
for i in "${!FPS_RUNGS[@]}"; do
  fps=${FPS_RUNGS[$i]}
  width=${WIDTH_RUNGS[$i]}
  if (( i > 0 )); then
    echo "demo.gif was ${gif_kb} KB -- retrying at ${fps}fps/${width}px" >&2
  fi
  if ! gif_pass "$fps" "$width"; then
    echo "ffmpeg gif conversion (${fps}fps, ${width}px) failed -- see $RUN_ROOT/ffmpeg-gif.log" >&2
    tail -n 40 "$RUN_ROOT/ffmpeg-gif.log" >&2
    exit 1
  fi
  gif_kb=$(( $(stat -c%s "$FF/demo.gif") / 1024 ))
  if (( gif_kb <= 4096 )); then
    fit=1
    break
  fi
done
if (( ! fit )); then
  echo "demo.gif is still ${gif_kb} KB after dropping to ${fps}fps/${width}px, over the 4 MB budget -- shorten the recording and re-run" >&2
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
