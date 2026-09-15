#!/usr/bin/env bash
# Fake `tailscale` for tests/guided-install.sh -- installed at
# /usr/local/bin/tailscale in that test's container image so serverjack-setup
# talks to this instead of a real tailscaled. State is per invoking Linux
# account (matching how a real tailnet node's identity is machine-wide but
# each test account here stands in for a separate machine):
#   ~/.faketailscale/state       "needslogin" (default) or "running"
#   ~/.faketailscale/login       tailnet login to report        (default tester@github);
#                                 present but EMPTY => a tagged device with no user login
#                                 at all -- "User": {} in the JSON, no entry for this uid
#                                 (C2's own fixture: a real tagged node genuinely has none)
#   ~/.faketailscale/tagged      file present => Self.Tags is non-empty
#   ~/.faketailscale/foreign     file present => `serve status` also reports an
#                                 existing https://:443 -> / mapping to something
#                                 else (a foreign, non-serverjack backend), for
#                                 check_serve_clash()
#   ~/.faketailscale/serveconfig one "<https_port> <path> <backend>" line per
#                                 mapping `serve --bg --https=P [--set-path=path] backend`
#                                 has set -- a REAL, mutable ServeConfig, not
#                                 a fixed fixture: `serve --https=P --set-path=path off`
#                                 removes the matching line, and `serve status`
#                                 reports whatever is actually in here, in the
#                                 real text format bin/serverjack-lib.sh's
#                                 serve_backend_for() parses. Without this,
#                                 every guided publish scenario could only ever
#                                 assert the FAILURE string (nothing here ever
#                                 recorded a successful publish), so
#                                 remove_owned_mapping()/uninstall.sh's route
#                                 removal were never actually exercised by any
#                                 guided test.
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
SERVECONFIG=$STATE_DIR/serveconfig
OPERATOR_FILE=/etc/faketailscale-operator
mkdir -p "$STATE_DIR"
touch "$SERVECONFIG"

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
      # login present-but-empty means "no user at all" for this uid -- a
      # real tagged device's own entry in `tailscale status --json` (C2).
      if [[ -f "$STATE_DIR/login" && -z $login ]]; then
        users='{}'
      else
        users=$(printf '{"%s":{"LoginName":"%s"}}' "$uid" "$login")
      fi
      printf '{"BackendState":"%s","Self":{"UserID":%s,"Tags":%s,"DNSName":"%s","TailscaleIPs":["100.64.1.%s"]},"User":%s}\n' \
        "$backend" "$uid" "$tags" "$dns" "$((uid % 250))" "$users"
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
    if [[ ${1:-} == status ]]; then
      if [[ -f "$STATE_DIR/foreign" ]]; then
        echo "https://$dns:443 (Funnel off)"
        echo "|-- / proxy http://127.0.0.1:9999"
      fi
      # Group the real (mutable) mappings by https port so each gets its own
      # "https://..." header line, matching the real text format.
      if [[ -s $SERVECONFIG ]]; then
        for p in $(awk '{print $1}' "$SERVECONFIG" | sort -u); do
          [[ -f "$STATE_DIR/foreign" && $p == 443 ]] && continue
          echo "https://$dns:$p (Funnel off)"
          awk -v p="$p" '$1==p{print "|-- " $2 " proxy " $3}' "$SERVECONFIG"
        done
      fi
      exit 0
    fi
    # Every other `serve` call is a mutation: parse the flags serverjack
    # ever actually passes, in any order --
    #   serve --bg --https=P BACKEND          (publish path "/")
    #   serve --https=P --set-path=PATH off    (remove one mapping)
    https=443
    path=/
    backend=""
    off=0
    for a in "$@"; do
      case "$a" in
        --https=*)    https=${a#--https=} ;;
        --set-path=*) path=${a#--set-path=} ;;
        --bg)         ;;
        off)          off=1 ;;
        *)            [[ -z $backend ]] && backend=$a ;;
      esac
    done
    # C4: proxying to a Unix socket genuinely needs root on a real
    # tailscale (verified on 1.102.3, see install.sh's own comment on this
    # -- the operator grant is not enough) -- simulate that here too, or
    # the whole guided "offer to run this with sudo" step (and its
    # declined-path test) has nothing real to exercise: every --unix
    # scenario would just silently succeed via the ordinary (non-root)
    # call, the same bug this fixture exists to catch.
    if (( ! off )) && [[ $backend == unix:* && $(id -u) -ne 0 ]]; then
      echo "401 Unauthorized: must be root, or be an operator and able to run 'sudo tailscale' to serve a path or Unix socket" >&2
      exit 1
    fi
    grep -v "^$https $path " "$SERVECONFIG" > "$SERVECONFIG.tmp" 2>/dev/null || true
    if (( ! off )) && [[ -n $backend ]]; then
      echo "$https $path $backend" >> "$SERVECONFIG.tmp"
    fi
    mv -f "$SERVECONFIG.tmp" "$SERVECONFIG"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
