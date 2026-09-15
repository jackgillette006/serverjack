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

# The generated theme's JSON, read from the real bin/serverjack at test time
# (not hand-typed here -- see docs/design/DESIGN.md's "Terminal theme") with
# the same empty SERVERJACK_TERM_THEME/TTYD_EXTRA_ARGS the "plain
# invocation" case below uses, so this is exactly what serverjack-ttyd's own
# `serverjack --print-theme` call will independently compute for it. `$here`
# inside serverjack-ttyd resolves to the real bin/, never $fake_bin (that
# only shadows `ttyd`), so this is the genuine article, not a stand-in.
theme_json=$(env SERVERJACK_TERM_THEME= TTYD_EXTRA_ARGS= python3 ../bin/serverjack --print-theme)
[[ -n $theme_json ]] || {
  echo "FAIL: bin/serverjack --print-theme printed nothing -- can't build the expected argv" >&2
  exit 1
}

# baseline: a plain invocation (no SERVERJACK_TERM_THEME, no
# TTYD_EXTRA_ARGS). baseline_no_theme: the same minus the generated
# -t theme=... -- what SERVERJACK_TERM_THEME=off, or a TTYD_EXTRA_ARGS that
# already sets its own theme, is expected to produce instead.
baseline_no_theme=(-i "$runtime/serverjack/ttyd.sock" -W -a -O
                    -t titleFixed=security-test -t disableLeaveAlert=true)
baseline=("${baseline_no_theme[@]}" -t "theme=$theme_json" "$attach")
baseline_no_theme+=("$attach")

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
check_argv "plain invocation carries the generated -t theme=..." argv_plain baseline

# SERVERJACK_TERM_THEME's off spellings (same as SERVERJACK_FX's) drop the
# generated theme entirely -- serverjack-ttyd's own --print-theme call
# prints nothing for them.
for term_theme_val in off 0 No FALSE; do
  capture_tt=$root/tt-$term_theme_val.argv
  env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_tt" \
    SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME=$term_theme_val TTYD_EXTRA_ARGS= \
    bash ../bin/serverjack-ttyd
  # shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
  mapfile -t argv_tt < "$capture_tt"
  check_argv "SERVERJACK_TERM_THEME=$term_theme_val drops the generated theme" argv_tt baseline_no_theme
done

# An explicit "on", and TTYD_EXTRA_ARGS truly absent (not just empty) rather
# than off, behave exactly like the plain/baseline case above.
for term_theme_val in on unset-entirely; do
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
  check_argv "SERVERJACK_TERM_THEME=$term_theme_val still carries the generated theme" argv_tt baseline
done

# A user's own -t theme=... in TTYD_EXTRA_ARGS must be the only theme flag
# in the final argv -- serverjack-ttyd's --print-theme call detects it (it
# reads the same TTYD_EXTRA_ARGS this process does) and prints nothing, so
# no second, conflicting -t theme=... gets prepended ahead of it.
capture_user_theme=$root/user-theme.argv
env PATH="$fake_bin:$PATH" XDG_RUNTIME_DIR="$runtime" TTYD_CAPTURE="$capture_user_theme" \
  SERVERJACK_TITLE=security-test SERVERJACK_TERM_THEME= \
  TTYD_EXTRA_ARGS='-t theme={\"background\":\"#123456\"}' \
  bash ../bin/serverjack-ttyd
# shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
mapfile -t argv_user_theme < "$capture_user_theme"
# shellcheck disable=SC2034  # read through check_argv's nameref, not by name here
expected_user_theme=("${baseline_no_theme[@]:0:${#baseline_no_theme[@]}-1}" \
  -t 'theme={"background":"#123456"}' "$attach")
check_argv "a user's own TTYD_EXTRA_ARGS theme is not joined by a generated one" \
  argv_user_theme expected_user_theme

# Safe TTYD_EXTRA_ARGS (no theme of its own) still reach ttyd, appended
# after the generated theme, with argument boundaries preserved.
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
