#!/usr/bin/env bash
# Observability shim for tests/guided-install.sh's "root-step prompts default
# to NO" scenario: logs every invocation to ~/.fake-sudo.log, then execs the
# REAL sudo so the call still (harmlessly) succeeds if it ever does happen --
# this is not a sudo replacement, just a way to prove whether serverjack-setup
# called sudo at all. Installed at /opt/fake-sudo-bin/sudo, NOT
# /usr/local/bin -- only the one scenario that needs it prepends that
# directory to its own PATH (via `docker exec -e PATH=...`); every other
# scenario keeps using the real /usr/bin/sudo already on the image's PATH.
echo "$*" >> "$HOME/.fake-sudo.log"
exec /usr/bin/sudo "$@"
