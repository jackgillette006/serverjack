#!/usr/bin/env bash
# Fake `tailscale` for tests/guided-install.sh -- installed at
# /usr/local/bin/tailscale in that test's container image so serverjack-setup
# talks to this instead of a real tailscaled. State is per invoking Linux
# account (matching how a real tailnet node's identity is machine-wide but
# each test account here stands in for a separate machine):
#   ~/.faketailscale/state    "needslogin" (default) or "running"
#   ~/.faketailscale/login    tailnet login to report                (default tester@github)
#   ~/.faketailscale/tagged   file present => Self.Tags is non-empty
#   ~/.faketailscale/foreign  file present => `serve status` reports an
#                             existing https://:443 -> / mapping to something
#                             else, for the check_serve_clash() scenario
# /etc/faketailscale-operator is the one genuinely machine-wide piece of
# state (root-writable only), mirroring how the real `tailscale set
# --operator` is machine-wide too.
set -Eeuo pipefail

# `sudo tailscale up` (what tailscale_login_flow() runs) invokes this AS
# ROOT, and sudo resets $HOME to root's by default -- so a plain $HOME here
# would read/write /root/.faketailscale instead of the real account's,
# meaning "up" writing "running" would never be seen by that account's own
# `status --json` calls. Found by exactly that happening (the login flow
# printing "Success." yet polling forever). $SUDO_USER is sudo's own record
# of who invoked it; resolve THEIR home instead when it's set.
real_home() {
  if [[ -n ${SUDO_USER:-} ]]; then
    getent passwd "$SUDO_USER" | cut -d: -f6
  else
    printf '%s' "$HOME"
  fi
}

STATE_DIR=$(real_home)/.faketailscale
STATE_FILE=$STATE_DIR/state
OPERATOR_FILE=/etc/faketailscale-operator
mkdir -p "$STATE_DIR"

state() {
  if [[ -f $STATE_FILE ]]; then cat "$STATE_FILE"; else echo needslogin; fi
}

uid=$(id -u)
login=tester@github
[[ -f "$STATE_DIR/login" ]] && login=$(cat "$STATE_DIR/login")
tagged=0
[[ -f "$STATE_DIR/tagged" ]] && tagged=1
dns="faketest.tail-fake.ts.net."

cmd=${1:-}
if [[ $# -gt 0 ]]; then shift; fi

case "$cmd" in
  status)
    if [[ ${1:-} == --json ]]; then
      st=$(state)
      if [[ $st == running ]]; then backend=Running; else backend=NeedsLogin; fi
      if (( tagged )); then tags='["tag:fake"]'; else tags=null; fi
      printf '{"BackendState":"%s","Self":{"UserID":%s,"Tags":%s,"DNSName":"%s","TailscaleIPs":["100.64.1.%s"]},"User":{"%s":{"LoginName":"%s"}}}\n' \
        "$backend" "$uid" "$tags" "$dns" "$((uid % 250))" "$uid" "$login"
      exit 0
    fi
    if [[ $(state) == running ]]; then
      echo "fake tailscale: running"
      exit 0
    fi
    echo "fake tailscale: Logged out." >&2
    exit 1
    ;;
  up)
    if [[ $(state) == running ]]; then
      echo "Already logged in."
      exit 0
    fi
    echo "To authenticate, visit:"
    echo ""
    echo "        https://login.tailscale.com/a/fake0123456789"
    echo ""
    sleep 3
    echo running > "$STATE_FILE"
    echo "Success."
    exit 0
    ;;
  debug)
    if [[ ${1:-} == prefs ]]; then
      op=""
      [[ -f $OPERATOR_FILE ]] && op=$(cat "$OPERATOR_FILE")
      printf '{"OperatorUser":"%s"}\n' "$op"
    fi
    exit 0
    ;;
  set)
    for a in "$@"; do
      case "$a" in
        --operator=*) printf '%s' "${a#--operator=}" > "$OPERATOR_FILE" ;;
      esac
    done
    exit 0
    ;;
  serve)
    if [[ ${1:-} == status ]] && [[ -f "$STATE_DIR/foreign" ]]; then
      echo "https://$dns:443 (Funnel off)"
      echo "|-- / proxy http://127.0.0.1:9999"
    fi
    # Every other serve subcommand (--bg --https=..., --set-path=... off,
    # ...) just succeeds -- this fake doesn't track machine-wide serve
    # state beyond the one "foreign" fixture above.
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
