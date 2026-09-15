#!/usr/bin/env bash
# Regression checks for serverjack-ttyd's private listener and extra-argument
# boundary. A fake ttyd records argv, so this never starts a listener.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"

tmp_base=${TMPDIR:-/tmp}
tmp_base=${tmp_base%/}
root=$(mktemp -d "$tmp_base/serverjack-wrapper-tests.XXXXXX")
cleanup() {
  case $root in
    "$tmp_base"/serverjack-wrapper-tests.*) rm -rf -- "$root" ;;
  esac
}
trap cleanup EXIT

fake_bin=$root/bin
runtime=$root/runtime
mkdir -m 700 "$fake_bin" "$runtime"
cat > "$fake_bin/ttyd" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$TTYD_CAPTURE"
SH
chmod 700 "$fake_bin/ttyd"

# The default theme JSON, exactly as bin/serverjack-ttyd builds it (kept as
# one variable here, not retyped inline below, so a copy/paste slip can't
# make this test lie about what ships).
theme_json='theme={"background":"#080f0e","foreground":"#e6f7e9","cursor":"#39ff88","cursorAccent":"#39ff88","selectionBackground":"rgba(57,255,136,0.3)","black":"#232e28","red":"#ff5f56","green":"#39ff88","yellow":"#ffc857","blue":"#58a6ff","magenta":"#c678ff","cyan":"#56d4c8","white":"#9fb3a8","brightBlack":"#3f5148","brightRed":"#ff7b72","brightGreen":"#6dffab","brightYellow":"#ffd479","brightBlue":"#7fb8ff","brightMagenta":"#d896ff","brightCyan":"#7ee8db","brightWhite":"#e6f7e9"}'

capture=$root/accepted.argv
env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture" \
  SERVERJACK_TITLE=security-test \
  TTYD_EXTRA_ARGS='-t screenReaderMode=true -m 4' \
  bash ../bin/serverjack-ttyd
mapfile -t argv < "$capture"
attach=$(readlink -f ../bin/tmux-attach.sh)
expected=(-i "$runtime/serverjack/ttyd.sock" -W -a -O
          -t titleFixed=security-test -t disableLeaveAlert=true
          -t "$theme_json"
          -t screenReaderMode=true -m 4 "$attach")
[[ ${#argv[@]} -eq ${#expected[@]} ]] || {
  echo "FAIL safe TTYD_EXTRA_ARGS argv count changed: ${argv[*]}" >&2; exit 1; }
for i in "${!expected[@]}"; do
  [[ ${argv[i]} == "${expected[i]}" ]] || {
    echo "FAIL argv[$i]: ${argv[i]} != ${expected[i]}" >&2; exit 1; }
done
echo "  PASS safe TTYD_EXTRA_ARGS preserve argument boundaries"
echo "  PASS default theme precedes TTYD_EXTRA_ARGS (so a user's own -t theme=... still wins)"

# SERVERJACK_TERM_THEME=off must drop -t theme=... and otherwise change
# nothing -- ttyd's own stock look.
capture_off=$root/off.argv
env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_off" \
  SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME=off \
  bash ../bin/serverjack-ttyd
mapfile -t argv_off < "$capture_off"
expected_off=(-i "$runtime/serverjack/ttyd.sock" -W -a -O
              -t titleFixed=security-test -t disableLeaveAlert=true "$attach")
[[ ${#argv_off[@]} -eq ${#expected_off[@]} ]] || {
  echo "FAIL SERVERJACK_TERM_THEME=off argv count changed: ${argv_off[*]}" >&2; exit 1; }
for i in "${!expected_off[@]}"; do
  [[ ${argv_off[i]} == "${expected_off[i]}" ]] || {
    echo "FAIL off argv[$i]: ${argv_off[i]} != ${expected_off[i]}" >&2; exit 1; }
done
echo "  PASS SERVERJACK_TERM_THEME=off drops the default theme"

# The other spellings SERVERJACK_FX accepts must opt out the same way.
for off_val in 0 No FALSE; do
  capture_alt=$root/off-$off_val.argv
  env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_alt" \
    SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME=$off_val \
    bash ../bin/serverjack-ttyd
  mapfile -t argv_alt < "$capture_alt"
  [[ ${#argv_alt[@]} -eq ${#expected_off[@]} ]] || {
    echo "FAIL SERVERJACK_TERM_THEME=$off_val argv count changed: ${argv_alt[*]}" >&2; exit 1; }
  echo "  PASS SERVERJACK_TERM_THEME=$off_val also opts out"
done

bad_args=('-i 0.0.0.0' '--port=9000' '-W' '-O' "'unterminated")
for i in "${!bad_args[@]}"; do
  rejected=$root/rejected-$i.argv
  if env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$rejected" \
      TTYD_EXTRA_ARGS="${bad_args[i]}" bash ../bin/serverjack-ttyd >/dev/null 2>&1; then
    echo "FAIL unsafe TTYD_EXTRA_ARGS accepted: ${bad_args[i]}" >&2
    exit 1
  fi
  [[ ! -e $rejected ]] || {
    echo "FAIL ttyd executed for unsafe TTYD_EXTRA_ARGS: ${bad_args[i]}" >&2
    exit 1
  }
  echo "  PASS rejected before exec: ${bad_args[i]}"
done

sock=$runtime/serverjack/ttyd.sock
printf 'do not remove\n' > "$sock"
if env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$root/file.argv" \
    bash ../bin/serverjack-ttyd >/dev/null 2>&1; then
  echo "FAIL ttyd started over a non-socket path" >&2
  exit 1
fi
[[ $(< "$sock") == 'do not remove' && ! -e $root/file.argv ]] || {
  echo "FAIL existing non-socket path was changed or ttyd executed" >&2
  exit 1
}
echo "  PASS existing non-socket ttyd path is preserved and refused"

# ------------------------------------------------------------------------
# Finding 4 (round 3): install.sh's port-busy check calls port_holder() and
# (via check_serve_clash-style code) serve_backend_for(), both from
# bin/serverjack-lib.sh, and assigns their output plainly
# (`holder=$(port_holder "$port")`) rather than inside an `if`/`&&`. `ss`
# without enough privilege to see another account's owning process prints a
# LISTEN line with NO "users:..." field at all, so port_holder()'s own
# internal `grep -o 'users:.*'` legitimately finds nothing and exits 1 --
# under `pipefail`, that fails port_holder()'s whole internal pipeline, and
# under `set -e` an unguarded `holder=$(port_holder ...)` in install.sh
# would abort the ENTIRE script silently, right before the "port busy"
# remedy message (the entire point of the check) is ever printed. The lib's
# `|| true` guards are what fix this; reproduced here directly against the
# lib (not by running install.sh itself, which would touch this host's own
# real ~/.config/serverjack, ~/.local/bin and systemd --user units -- never
# allowed) using install.sh's own decision logic verbatim, so a regression
# in either the lib or that logic is caught.
echo "== port-busy detection survives an ss line with no \"users:\" field (finding 4)"
port_bin=$root/portfake
mkdir -m 700 "$port_bin"
test_port=19191
cat > "$port_bin/ss" <<SH
#!/usr/bin/env bash
# Mimics an unprivileged \`ss -ltnp\`: the port shows up as LISTEN, but the
# owning process cannot be named (no "users:..." field) -- exactly what
# port_holder()'s own \`grep -o 'users:.*'\` then finds nothing to match.
echo 'LISTEN 0      128          0.0.0.0:$test_port        0.0.0.0:*'
SH
chmod 700 "$port_bin/ss"
cat > "$port_bin/tailscale" <<'SH'
#!/usr/bin/env bash
# Mimics tailscale with nothing configured yet: `serve status` exits
# non-zero and prints nothing, same as a fresh account -- serve_backend_for
# must not abort on this either (its own `|| true` guard).
exit 1
SH
chmod 700 "$port_bin/tailscale"

set +e
portcheck_out=$(
  exec 2>&1
  set -Eeuo pipefail
  # shellcheck source=bin/serverjack-lib.sh
  source ../bin/serverjack-lib.sh
  export PATH="$port_bin:$PATH"

  ! port_free "$test_port" || { echo "internal test error: fake ss did not make the port look busy" >&2; exit 9; }

  # install.sh's own remedy() and the busy-port branch it feeds, copied
  # verbatim (minus the real `systemctl --user is-active` gate, which this
  # host-side test must never touch -- see the comment above): the part
  # under test is that `holder=$(port_holder ...)` does not abort anything.
  free_pair() { local p=$1; while (( p < 65000 )); do port_free "$p" && port_free "$((p+1))" && { printf '%s' "$p"; return; }; p=$((p+10)); done; printf '%s' "$1"; }
  free_https() { local p; for p in 443 8443 10000; do [[ -z "$(serve_backend_for "$p" /)" ]] && { printf '%s' "$p"; return; }; done; printf '8443'; }
  remedy() { echo "$1" >&2; echo "Pick a free port and a free HTTPS port for this account, e.g.:" >&2; echo "  bash /fake/install.sh --port $(free_pair $((test_port+10))) --https-port $(free_https)" >&2; }

  holder=$(port_holder "$test_port")
  # The regression this guards: without the lib's `|| true`, the line above
  # would have already killed this subshell under `set -e` -- nothing past
  # it (including the marker echo below) would ever run.
  echo "PORT_HOLDER_SURVIVED holder='$holder'"
  if [[ $holder == *'"python3"'* || $holder == *'"ttyd"'* || $holder == *'"serverjack"'* ]]; then
    whose="another process (probably another user's serverjack)"
  else
    whose="another process"
  fi
  remedy "port $test_port is in use by $whose: $holder"
  exit 1
)
rc=$?
set -e
[[ $rc -eq 1 ]] && echo "  PASS the port-busy check exits 1 (not an unrelated pipefail crash)" \
  || { echo "  FAIL the port-busy check exits 1 -- got rc=$rc: $portcheck_out" >&2; exit 1; }
[[ $portcheck_out == *"PORT_HOLDER_SURVIVED holder=''"* ]] && echo "  PASS port_holder() returned an empty holder (no \"users:\" field) without aborting the script" \
  || { echo "  FAIL port_holder() returned control past the missing-\"users:\" case -- got: $portcheck_out" >&2; exit 1; }
[[ $portcheck_out == *"port $test_port is in use by another process"* ]] && echo "  PASS the port-busy remedy was printed" \
  || { echo "  FAIL the port-busy remedy was printed -- got: $portcheck_out" >&2; exit 1; }
