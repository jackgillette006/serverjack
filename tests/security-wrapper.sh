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

capture=$root/accepted.argv
env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture" \
  SERVERJACK_TITLE=security-test \
  TTYD_EXTRA_ARGS='-t screenReaderMode=true -m 4' \
  bash ../bin/serverjack-ttyd
mapfile -t argv < "$capture"
attach=$(readlink -f ../bin/tmux-attach.sh)
expected=(-i "$runtime/serverjack/ttyd.sock" -W -a -O
          -t titleFixed=security-test -t disableLeaveAlert=true
          -t screenReaderMode=true -m 4 "$attach")
[[ ${#argv[@]} -eq ${#expected[@]} ]] || {
  echo "FAIL safe TTYD_EXTRA_ARGS argv count changed: ${argv[*]}" >&2; exit 1; }
for i in "${!expected[@]}"; do
  [[ ${argv[i]} == "${expected[i]}" ]] || {
    echo "FAIL argv[$i]: ${argv[i]} != ${expected[i]}" >&2; exit 1; }
done
echo "  PASS safe TTYD_EXTRA_ARGS preserve argument boundaries"

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
