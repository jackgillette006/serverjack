#!/usr/bin/env bash
# Host-side (no Docker) regression test for C2: bin/serverjack-setup's
# read_tailscale_self() used to print all four fields tab-separated on ONE
# line and split it with `IFS=$'\t' read` -- tab is one of bash's built-in
# "IFS whitespace" characters (space/tab/newline) regardless of what else
# is in $IFS, so consecutive delimiters still collapse and leading/trailing
# ones still get stripped, exactly like the default IFS does with spaces.
# A tagged node with no User login at all (its own Tags-only entry, no
# "User" map entry for that uid -- a real, common case for a headless/
# server node) printed "1\t\t<dns>\t<ip>": the double-tab collapsed, so
# every field after the empty one silently shifted -- TS_LOGIN got the DNS
# name, TS_DNS got the IP, TS_IP ended up empty.
#
# bin/serverjack-setup is sourced directly (guarded at its own end so this
# doesn't also run the full guided flow) with a fake `tailscale` on PATH.
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO=$(cd .. && pwd)

failures=0
result() {  # $1 label  $2 expected  $3 got
  if [[ $3 == "$2" ]]; then
    echo "  PASS $1"
  else
    echo "  FAIL $1 -- got '$3', wanted '$2'"
    failures=$((failures + 1))
  fi
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/serverjack-read-ts-self-test.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/fakebin"
FAKE_JSON="$WORK/fake.json"
cat > "$WORK/fakebin/tailscale" <<SH
#!/usr/bin/env bash
if [[ "\$1 \$2" == "status --json" ]]; then
  cat "$FAKE_JSON"
  exit 0
fi
exit 1
SH
chmod 755 "$WORK/fakebin/tailscale"
PATH="$WORK/fakebin:$PATH"

# shellcheck disable=SC1090
source "$REPO/bin/serverjack-setup"

echo "================================================================"
echo "(a) a tagged node with NO user login at all (C2's exact regression)"
cat > "$FAKE_JSON" <<'JSON'
{"BackendState":"Running","Self":{"UserID":12345,"Tags":["tag:fake"],"DNSName":"test-host.example.ts.net.","TailscaleIPs":["100.64.0.10"]},"User":{}}
JSON
read_tailscale_self
result "(a) TS_TAGGED" "1" "$TS_TAGGED"
result "(a) TS_LOGIN is genuinely empty (not the DNS name)" "" "$TS_LOGIN"
result "(a) TS_DNS is the real DNS name (not the IP)" "test-host.example.ts.net" "$TS_DNS"
result "(a) TS_IP is the real IP (not empty)" "100.64.0.10" "$TS_IP"

echo "================================================================"
echo "(b) an untagged node WITH a login (the ordinary case still works)"
cat > "$FAKE_JSON" <<'JSON'
{"BackendState":"Running","Self":{"UserID":999,"Tags":null,"DNSName":"alice-box.example.ts.net.","TailscaleIPs":["100.64.0.20"]},"User":{"999":{"LoginName":"alice@github"}}}
JSON
read_tailscale_self
result "(b) TS_TAGGED" "0" "$TS_TAGGED"
result "(b) TS_LOGIN" "alice@github" "$TS_LOGIN"
result "(b) TS_DNS" "alice-box.example.ts.net" "$TS_DNS"
result "(b) TS_IP" "100.64.0.20" "$TS_IP"

echo "================================================================"
echo "(c) tailscale unreachable/malformed output -- clean, empty defaults"
cat > "$FAKE_JSON" <<'JSON'
not valid json at all
JSON
read_tailscale_self
result "(c) TS_TAGGED defaults to 0" "0" "$TS_TAGGED"
result "(c) TS_LOGIN defaults to empty" "" "$TS_LOGIN"
result "(c) TS_DNS defaults to empty" "" "$TS_DNS"
result "(c) TS_IP defaults to empty" "" "$TS_IP"

echo
if (( failures > 0 )); then
  echo "$failures read_tailscale_self check(s) failed" >&2
fi
exit $(( failures > 0 ))
