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

attach=$(readlink -f ../bin/tmux-attach.sh)
# The terminal's color theme is generated in bin/serverjack now (from TOKENS,
# see _term_theme()) and passed to ttyd on the iframe URL, not as a -t flag
# here -- this file no longer emits or reads SERVERJACK_TERM_THEME at all, so
# there is nothing theme-shaped left to compare in this argv. baseline is
# what every plain invocation below is expected to produce.
baseline=(-i "$runtime/serverjack/ttyd.sock" -W -a -O
          -t titleFixed=security-test -t disableLeaveAlert=true "$attach")

# Compares an argv (by nameref) against an expected array, element by
# element and by length, used by every block below so a mismatch anywhere
# in the middle can't hide behind a count-only check.
check_argv() {
  local label=$1 got_name=$2 want_name=$3
  local -n got=$got_name want=$want_name
  if [[ ${#got[@]} -ne ${#want[@]} ]]; then
    echo "FAIL $label: argv count ${#got[@]} != ${#want[@]}  -- got: ${got[*]}" >&2
    exit 1
  fi
  local i
  for i in "${!want[@]}"; do
    if [[ ${got[i]} != "${want[i]}" ]]; then
      echo "FAIL $label: argv[$i] ${got[i]} != ${want[i]}  -- got: ${got[*]}" >&2
      exit 1
    fi
  done
  echo "  PASS $label"
}

# Every invocation below isolates SERVERJACK_TERM_THEME= and TTYD_EXTRA_ARGS=
# explicitly: without that, a maintainer's own shell (this one included --
# both have been found already set in the environment a real terminal
# session runs in) leaks its own value in and can make an "off"/"safe" case
# below pass or fail for the wrong reason.
capture=$root/plain.argv
env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture" \
  SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME= TTYD_EXTRA_ARGS= \
  bash ../bin/serverjack-ttyd
# shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
mapfile -t argv_plain < "$capture"
check_argv "plain invocation matches the baseline argv" argv_plain baseline

# Regression guard for the refactor: SERVERJACK_TERM_THEME (any of the
# spellings SERVERJACK_FX accepts, or an unrelated value) must make no
# difference here any more -- it's read in bin/serverjack, not this file.
for term_theme_val in off 0 No FALSE on unset-entirely; do
  capture_tt=$root/tt-$term_theme_val.argv
  if [[ $term_theme_val == unset-entirely ]]; then
    env -u SERVERJACK_TERM_THEME PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_tt" \
      SERVERJACK_TITLE=security-test TTYD_EXTRA_ARGS= \
      bash ../bin/serverjack-ttyd
  else
    env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_tt" \
      SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME=$term_theme_val TTYD_EXTRA_ARGS= \
      bash ../bin/serverjack-ttyd
  fi
  # shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
  mapfile -t argv_tt < "$capture_tt"
  check_argv "SERVERJACK_TERM_THEME=$term_theme_val has no effect here" argv_tt baseline
done

# Safe TTYD_EXTRA_ARGS still reach ttyd, appended after the baseline flags,
# with argument boundaries preserved.
capture_extra=$root/extra.argv
env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_extra" \
  SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME= \
  TTYD_EXTRA_ARGS='-t screenReaderMode=true -m 4' \
  bash ../bin/serverjack-ttyd
# shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
mapfile -t argv_extra < "$capture_extra"
# shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
expected_extra=("${baseline[@]:0:${#baseline[@]}-1}" -t screenReaderMode=true -m 4 "$attach")
check_argv "safe TTYD_EXTRA_ARGS preserve argument boundaries" argv_extra expected_extra

bad_args=('-i 0.0.0.0' '--port=9000' '-W' '-O' "'unterminated")
for i in "${!bad_args[@]}"; do
  rejected=$root/rejected-$i.argv
  if env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$rejected" \
      SERVERJACK_TERM_THEME= TTYD_EXTRA_ARGS="${bad_args[i]}" bash ../bin/serverjack-ttyd >/dev/null 2>&1; then
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
    SERVERJACK_TERM_THEME= TTYD_EXTRA_ARGS= bash ../bin/serverjack-ttyd >/dev/null 2>&1; then
  echo "FAIL ttyd started over a non-socket path" >&2
  exit 1
fi
[[ $(< "$sock") == 'do not remove' && ! -e $root/file.argv ]] || {
  echo "FAIL existing non-socket path was changed or ttyd executed" >&2
  exit 1
}
echo "  PASS existing non-socket ttyd path is preserved and refused"
