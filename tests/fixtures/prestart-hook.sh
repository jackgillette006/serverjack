#!/usr/bin/env bash
# Test-only hook for tests/guided-install.sh (finding B1): pointed to by
# SERVERJACK_TEST_PRESTART_HOOK, install.sh runs this with the env file's
# path as $1 at the exact moment it is about to start units / publish (see
# install.sh's own comment on that hook). Records whether SERVERJACK_ALLOW
# is already present on disk at that instant, so the test can assert the
# allow-list was persisted BEFORE anything could answer a request, not
# after (the bug B1 fixes: a post-hoc write left a window with no
# restriction in force).
set -Eeuo pipefail
env_file=$1
marker="$HOME/.prestart-hook-result"
if grep -q '^SERVERJACK_ALLOW=' "$env_file" 2>/dev/null; then
  echo "ALLOW_PRESENT" > "$marker"
else
  echo "ALLOW_ABSENT" > "$marker"
fi
