#!/usr/bin/env bash
# Headless-browser tests, entirely in containers (needs docker; nothing else
# has to be running -- the harness starts its own serverjack and ttyd).
#   bash tests/run.sh            # all suites
#   bash tests/run.sh pwclip     # one suite
#
# There is one listener per instance now: serverjack serves the terminal itself
# by proxying /term/ to ttyd's Unix socket, so the browsers talk straight to
# serverjack and no nginx is involved. It starts, in tcp mode:
#   127.0.0.1:7690  serverjack + its own ttyd   the ordinary instance
#   127.0.0.1:7692  serverjack + its own ttyd   SERVERJACK_ALLOW=alice@example.com,
#                                               driven by tests/pwauth.py
#   127.0.0.1:7694  serverjack   a throwaway instance for the autostart check
# Each instance gets its OWN scratch XDG_RUNTIME_DIR (shots/rt, shots/rt-auth,
# shots/rt-auto) so each has its own ttyd.sock and nothing touches a real
# install's runtime dir.
#
# Then a scratch tmux session "pwtest", and Chromium / Firefox / WebKit (iPhone
# 14 emulation) driven with Playwright, reading the tmux pane from the host
# socket to prove keystrokes really arrived. Screenshots land in tests/shots/.
# Emulated WebKit is NOT iOS Safari.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
IMG=mcr.microsoft.com/playwright/python:v1.62.0-noble
SOCK=/tmp/tmux-$(id -u)
export PATH="$HOME/.local/bin:$PATH"
mkdir -p shots
# One scratch runtime dir per instance: ttyd.sock lives in it, and two ttyds
# cannot share one. 0700, exactly as serverjack insists on.
RT=$PWD/shots/rt
RT_AUTH=$PWD/shots/rt-auth
RT_AUTO=$PWD/shots/rt-auto
for d in "$RT" "$RT_AUTH" "$RT_AUTO"; do rm -rf "$d"; mkdir -p "$d"; chmod 700 "$d"; done
pids=()
cleanup() {
  for p in "${pids[@]:-}"; do [[ -n $p ]] && kill "$p" 2>/dev/null; done
  for port in 7690 7692 7694; do
    for p in $(ss -ltnp 2>/dev/null | grep ":$port " | grep -o 'pid=[0-9]*' | cut -d= -f2); do kill "$p" 2>/dev/null; done
  done
  pkill -f "ttyd -i $PWD/shots/rt" 2>/dev/null
  tmux kill-session -t pwtest 2>/dev/null
  # sessions the landing-page suite creates: "echo ..." -> echo/echo-2,
  # the fake tool's Open -> fake/fake-2, its action -> hello/hello-2
  for n in $(tmux ls -F '#{session_name}' 2>/dev/null | grep -E '^(echo|fake|fake2|hello|landren-[0-9]+|pwauto)(-[0-9]+)?$'); do
    tmux kill-session -t "=$n" 2>/dev/null
  done
}
trap cleanup EXIT; cleanup
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
# SERVERJACK_TRUST_UIDS=101 is not needed to reach anything here any more (no
# proxy in front), but the peer-uid check below still proves it works.
common=(SERVERJACK_LISTEN=tcp SERVERJACK_TITLE=test SERVERJACK_CONFIG="$CFG"
        SERVERJACK_TOOLS=fake,fake2 SERVERJACK_TRUST_UIDS=101)
env "${common[@]}" XDG_RUNTIME_DIR="$RT" SERVERJACK_PORT=7690 \
    python3 ../bin/serverjack >shots/web.log 2>&1 & pids+=($!)
env "${common[@]}" XDG_RUNTIME_DIR="$RT" \
    bash ../bin/serverjack-ttyd >shots/ttyd.log 2>&1 & pids+=($!)
# Second instance: same code, restricted to one tailnet login, own runtime dir.
# screenReaderMode puts xterm's text in the DOM (it renders to a canvas
# otherwise), which is how pwauth reads messages off the terminal. It also
# proves TTYD_EXTRA_ARGS still reaches ttyd through the wrapper.
env "${common[@]}" XDG_RUNTIME_DIR="$RT_AUTH" SERVERJACK_ALLOW=alice@example.com \
    SERVERJACK_PORT=7692 python3 ../bin/serverjack >shots/web-auth.log 2>&1 & pids+=($!)
env "${common[@]}" XDG_RUNTIME_DIR="$RT_AUTH" SERVERJACK_ALLOW=alice@example.com \
    TTYD_EXTRA_ARGS='-t screenReaderMode=true' \
    bash ../bin/serverjack-ttyd >shots/ttyd-auth.log 2>&1 & pids+=($!)
tmux new-session -d -s pwtest -x 120 -y 30 -c "$HOME"
sleep 2
curl -sf -o /dev/null http://127.0.0.1:7690/ || { echo "landing not up (see shots/web.log)" >&2; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:7690/term/ || { echo "terminal not reachable through serverjack (see shots/ttyd.log)" >&2; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:7692/healthz || { echo "restricted instance not up (see shots/web-auth.log)" >&2; exit 1; }

# Host validation: a name we don't answer to must not reach any route, so a
# rebinding attack can't drive this from a browser it tricked.
echo "== Host validation (host-side)"
hostcode() { curl -s -o /dev/null -w '%{http_code}' -H "Host: $1" "http://127.0.0.1:7690$2"; }
# (no `set --` here: it would clobber $@, which still holds the suite names)
for probe_path in / /healthz /term/; do
  got=$(hostcode evil.example "$probe_path")
  [[ $got == 421 ]] && echo "  PASS Host: evil.example $probe_path -> 421" \
                    || echo "  FAIL Host: evil.example $probe_path -> $got, wanted 421"
done
got=$(hostcode "localhost:7690" /healthz)
[[ $got == 200 ]] && echo "  PASS Host: localhost:7690 /healthz -> 200" || echo "  FAIL Host: localhost:7690 -> $got"

# Peer-uid check, from the host: another local account must be refused, we must
# not be. Playwright can't help -- its container runs as root, which is allowed
# on purpose (that is how tailscaled reaches us).
echo "== peer-uid (host-side)"
uidcheck() {   # $1 label, $2 path, $3 expected code, $4.. docker user flags
  local got
  got=$(docker run --rm --network host "${@:4}" curlimages/curl:latest \
          -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:7690$2" 2>/dev/null | tail -1)
  [[ $got == "$3" ]] && echo "  PASS $1" || echo "  FAIL $1  -- got $got, wanted $3"
}
own=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7690/)
[[ $own == 200 ]] && echo "  PASS the owning account gets in" || echo "  FAIL the owning account gets in  -- got $own"
uidcheck "another local user (uid 65534) is refused" / 403 --user 65534
uidcheck "...and cannot reach the terminal either" /term/ 403 --user 65534
uidcheck "root (tailscaled's uid) gets in" / 200 --user 0
uidcheck "the trusted proxy uid (101) gets in" / 200 --user 101

# The terminal's WebSocket, through serverjack's proxy: same origin accepted,
# foreign origin refused by ttyd -O (which still sees the real Host/Origin
# because the proxy forwards them verbatim).
echo "== terminal websocket (host-side)"
python3 ../bin/ttyd-ws-check.py http://127.0.0.1:7690/term/ \
  && echo "  PASS same-origin 101, foreign origin refused" \
  || echo "  FAIL websocket origin behaviour through the proxy"

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
auto=(SERVERJACK_LISTEN=tcp SERVERJACK_TITLE=test XDG_RUNTIME_DIR="$RT_AUTO" SERVERJACK_CONFIG="$ACFG"
      SERVERJACK_TOOLS=fakesrv SERVERJACK_PORT=7694 SERVERJACK_AUTOSTART_DELAY=2)
env "${auto[@]}" python3 ../bin/serverjack >shots/web-auto.log 2>&1 & pids+=($!)
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
docker run --rm --network host --add-host pypi.org:151.101.0.223 \
  --add-host files.pythonhosted.org:151.101.0.223 \
  -v "$PWD:/w" -w /w -v "$SOCK:$SOCK" -e TMUX_SOCK="$SOCK/default" "$IMG" bash -c '
  pip install -q --timeout 15 --retries 1 playwright==1.62.0 >/dev/null 2>&1
  (apt-get -qq update && apt-get -qq install -y tmux) >/dev/null 2>&1
  for s in '"${suites[*]}"'; do echo "== $s"; python3 "$s.py"; done' 2>&1 | grep -v 'GL Driver\|maybe unknown option'
