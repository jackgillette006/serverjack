#!/usr/bin/env bash
# Headless-browser tests, entirely in containers (needs docker; nothing else
# has to be running -- the harness starts its own serverjack and ttyd).
#   bash tests/run.sh            # all suites
#   bash tests/run.sh pwclip     # one suite
#
# It starts, all in tcp mode on scratch ports and with a scratch runtime dir
# (shots/rt) so the token secret is never the user's real one:
#   127.0.0.1:7690  serverjack        \ the ordinary instance, no identity check
#   127.0.0.1:7691  ttyd              /
#   127.0.0.1:7692  serverjack        \ SERVERJACK_ALLOW=alice@example.com,
#   127.0.0.1:7693  ttyd              / driven by tests/pwauth.py
#   127.0.0.1:7694  serverjack        a throwaway instance for the autostart
#                                     check below, started and killed here
#   127.0.0.1:7699 / :7698  nginx, mimicking tailscale serve's routing
#     (/term/ -> ttyd with the prefix stripped, / -> the landing page)
# plus a scratch tmux session "pwtest", then drives Chromium / Firefox / WebKit
# (iPhone 14 emulation) with Playwright, reading the tmux pane from the host
# socket to prove keystrokes really arrived. Screenshots land in tests/shots/.
# Emulated WebKit is NOT iOS Safari.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble
SOCK=/tmp/tmux-$(id -u)
export PATH="$HOME/.local/bin:$PATH"
mkdir -p shots
# Scratch runtime dir: <this>/serverjack holds the sockets (unused here, we run
# tcp) and "secret", the HMAC key behind the terminal tokens. Keeping it out of
# $XDG_RUNTIME_DIR means a test run cannot disturb a real install's tokens.
RT=$PWD/shots/rt
rm -rf "$RT"; mkdir -p "$RT"; chmod 700 "$RT"
cleanup() {
  docker rm -f tw-proxy >/dev/null 2>&1
  for port in 7690 7691 7692 7693 7694; do
    for p in $(ss -ltnp 2>/dev/null | grep ":$port " | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill "$p" 2>/dev/null; done
  done
  tmux kill-session -t pwtest 2>/dev/null
  # sessions the landing-page suite creates: "echo ..." -> echo/echo-2,
  # the fake tool's Open -> fake/fake-2, its action -> hello/hello-2
  for n in $(tmux ls -F '#{session_name}' 2>/dev/null | grep -E '^(echo|fake|fake2|hello|landren-[0-9]+|pwauto)(-[0-9]+)?$'); do
    tmux kill-session -t "=$n" 2>/dev/null
  done
}
trap cleanup EXIT; cleanup
cp nginx.conf shots/nginx.conf
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
# nginx:alpine runs its workers as uid 101, and serverjack's peer-uid check
# refuses anyone but root and its own user -- so the proxy's uid has to be
# trusted here, exactly as examples/nginx.conf tells a real deployment to.
common=(SERVERJACK_LISTEN=tcp SERVERJACK_TITLE=test XDG_RUNTIME_DIR="$RT" SERVERJACK_CONFIG="$CFG"
        SERVERJACK_TOOLS=fake,fake2 SERVERJACK_TRUST_UIDS=101)
(env "${common[@]}" SERVERJACK_PORT=7690 python3 ../bin/serverjack >shots/web.log 2>&1 &)
(env "${common[@]}" TTYD_PORT=7691 bash ../bin/serverjack-ttyd >shots/ttyd.log 2>&1 &)
# Second pair: same code, restricted to one tailnet login.
(env "${common[@]}" SERVERJACK_ALLOW=alice@example.com SERVERJACK_PORT=7692 python3 ../bin/serverjack >shots/web-auth.log 2>&1 &)
# screenReaderMode puts xterm's text in the DOM (it renders to a canvas
# otherwise), which is how pwauth reads the refusal message off the terminal.
# It also proves TTYD_EXTRA_ARGS still reaches ttyd through the wrapper.
(env "${common[@]}" SERVERJACK_ALLOW=alice@example.com TTYD_PORT=7693 \
   TTYD_EXTRA_ARGS='-t screenReaderMode=true' bash ../bin/serverjack-ttyd >shots/ttyd-auth.log 2>&1 &)
docker run -d --rm --name tw-proxy --network host -v "$PWD/shots/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:alpine >/dev/null
tmux new-session -d -s pwtest -x 120 -y 30 -c "$HOME"
sleep 2
curl -sf -o /dev/null http://127.0.0.1:7699/ || { echo "proxy/landing not up (see shots/web.log)" >&2; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:7699/term/ || { echo "ttyd not reachable through proxy (see shots/ttyd.log)" >&2; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:7698/healthz || { echo "restricted instance not up (see shots/web-auth.log)" >&2; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:7698/term/ || { echo "restricted ttyd not up (see shots/ttyd-auth.log)" >&2; exit 1; }
# Peer-uid check, from the host: another local account must be refused, we must
# not be. Playwright can't help -- its container runs as root, which is allowed
# on purpose (that is how tailscaled reaches us). 7690 is hit directly, around
# the nginx whose uid is trusted above.
echo "== peer-uid (host-side)"
uidcheck() {   # $1 label, $2 expected code, $3.. docker user flags
  local got
  got=$(docker run --rm --network host "${@:3}" curlimages/curl:latest \
          -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7690/ 2>/dev/null | tail -1)
  [[ $got == "$2" ]] && echo "  PASS $1" || echo "  FAIL $1  -- got $got, wanted $2"
}
own=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7690/)
[[ $own == 200 ]] && echo "  PASS the owning account gets in" || echo "  FAIL the owning account gets in  -- got $own"
uidcheck "another local user (uid 65534) is refused" 403 --user 65534
uidcheck "root (tailscaled's uid) gets in" 200 --user 0
uidcheck "the trusted proxy uid (101) gets in" 200 --user 101

# ---------------------------------------------------------------- autostart
# autostart.json is a boot-time thing, so it gets its own throwaway instance
# rather than a browser: a config dir with one fake tool whose "server" is
# `sleep 300`, an autostart entry for it, and a 2-second delay instead of 15.
# Passing means the tmux session appeared without anyone pressing a button.
echo "== autostart (host-side)"
ACFG=$PWD/shots/cfg-auto
rm -rf "$ACFG"; mkdir -p "$ACFG"
cat > "$ACFG/tools.json" <<'JSON'
[{"id": "fakesrv", "label": "Fake server", "bin": "true", "run": "bash",
  "server": {"label": "Fake server", "cmd": "sleep 300", "session": "pwauto"}}]
JSON
cat > "$ACFG/autostart.json" <<'JSON'
[{"tool": "fakesrv", "kind": "server", "dir": "."}]
JSON
tmux kill-session -t =pwauto 2>/dev/null
auto=(SERVERJACK_LISTEN=tcp SERVERJACK_TITLE=test XDG_RUNTIME_DIR="$RT" SERVERJACK_CONFIG="$ACFG"
      SERVERJACK_TOOLS=fakesrv SERVERJACK_PORT=7694 SERVERJACK_AUTOSTART_DELAY=2)
(env "${auto[@]}" python3 ../bin/serverjack >shots/web-auto.log 2>&1 &)
for i in $(seq 1 30); do tmux has-session -t =pwauto 2>/dev/null && break; sleep 0.5; done
if tmux has-session -t =pwauto 2>/dev/null; then
  echo "  PASS autostart started the fake server's session"
  grep -q 'autostart: started fakesrv server' shots/web-auto.log \
    && echo "  PASS ...and said so on stderr" \
    || echo "  FAIL ...and said so on stderr  -- $(tail -1 shots/web-auto.log)"
else
  echo "  FAIL autostart started the fake server's session  -- $(tail -3 shots/web-auto.log | tr '\n' ' ')"
fi
tmux kill-session -t =pwauto 2>/dev/null
for p in $(ss -ltnp 2>/dev/null | grep ':7694 ' | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill "$p" 2>/dev/null; done

suites=("$@"); [[ ${#suites[@]} -eq 0 ]] && suites=(pwtest pwclip pwmobile pwpop pwland pwauth pwwin)
docker run --rm --network host -v "$PWD:/w" -w /w -v "$SOCK:$SOCK" -e TMUX_SOCK="$SOCK/default" "$IMG" bash -c '
  pip install -q playwright==1.62.0 >/dev/null 2>&1
  (apt-get -qq update && apt-get -qq install -y tmux) >/dev/null 2>&1
  for s in '"${suites[*]}"'; do echo "== $s"; python3 "$s.py"; done' 2>&1 | grep -v 'GL Driver\|maybe unknown option'
