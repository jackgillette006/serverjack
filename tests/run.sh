#!/usr/bin/env bash
# Headless-browser tests, entirely in containers (needs docker + a running ttyd).
#   bash tests/run.sh            # all suites
#   bash tests/run.sh pwclip     # one suite
# Starts a throwaway serverjack on 127.0.0.1:7690, an nginx on 127.0.0.1:7699
# that mimics tailscale serve routing (/term/ -> live ttyd on $TTYD_PORT with
# the prefix stripped, / -> 7690), a scratch tmux session "pwtest", then drives
# Chromium / Firefox / WebKit (iPhone 14 emulation) with Playwright, reading
# the tmux pane from the host socket to prove keystrokes really arrived.
# Screenshots land in tests/shots/. Emulated WebKit is NOT iOS Safari.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble
TTYD_PORT=${TTYD_PORT:-7681}
SOCK=/tmp/tmux-$(id -u)
mkdir -p shots
cleanup() {
  docker rm -f tw-proxy >/dev/null 2>&1
  for p in $(ss -ltnp 2>/dev/null | grep ':7690 ' | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill "$p" 2>/dev/null; done
  tmux kill-session -t pwtest 2>/dev/null
  # sessions the landing-page suite creates: "echo ..." -> echo/echo-2,
  # the fake tool's Open -> fake/fake-2, its action -> hello/hello-2
  for n in $(tmux ls -F '#{session_name}' 2>/dev/null | grep -E '^(echo|fake|fake2|hello)(-[0-9]+)?$'); do
    tmux kill-session -t "=$n" 2>/dev/null
  done
}
trap cleanup EXIT; cleanup
sed "s/7681/$TTYD_PORT/" nginx.conf > shots/nginx.conf
# A throwaway config dir with two fake agents, so the agent-card tests are
# deterministic and never touch a real coding CLI or the user's shortcuts.
CFG=$PWD/shots/cfg
mkdir -p "$CFG"; rm -f "$CFG/shortcuts.json"
cat > "$CFG/tools.json" <<'JSON'
[{"id": "fake", "label": "Fake tool", "bin": "true", "login": "echo LOGIN_RAN",
  "login_check": "true", "run": "bash",
  "actions": [{"label": "hello", "cmd": "echo ACTION_RAN"}]},
 {"id": "fake2", "label": "Fake two", "bin": "true", "run": "bash"}]
JSON
(SERVERJACK_PORT=7690 SERVERJACK_TITLE=test SERVERJACK_CONFIG=$CFG SERVERJACK_TOOLS=fake,fake2 \
   python3 ../bin/serverjack >shots/web.log 2>&1 &)
docker run -d --rm --name tw-proxy --network host -v "$PWD/shots/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:alpine >/dev/null
tmux new-session -d -s pwtest -x 120 -y 30 -c "$HOME"
sleep 1.5
curl -sf -o /dev/null http://127.0.0.1:7699/ || { echo "proxy/landing not up" >&2; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:7699/term/ || { echo "ttyd not reachable through proxy (is ttyd running on $TTYD_PORT?)" >&2; exit 1; }
suites=("$@"); [[ ${#suites[@]} -eq 0 ]] && suites=(pwtest pwclip pwmobile pwpop pwland)
docker run --rm --network host -v "$PWD:/w" -w /w -v "$SOCK:$SOCK" -e TMUX_SOCK="$SOCK/default" "$IMG" bash -c '
  pip install -q playwright==1.62.0 >/dev/null 2>&1
  (apt-get -qq update && apt-get -qq install -y tmux) >/dev/null 2>&1
  for s in '"${suites[*]}"'; do echo "== $s"; python3 "$s.py"; done' 2>&1 | grep -v 'GL Driver\|maybe unknown option'
