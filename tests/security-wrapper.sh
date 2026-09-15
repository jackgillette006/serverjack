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
