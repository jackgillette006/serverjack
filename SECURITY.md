# Security policy

serverjack gives every authorized visitor an interactive shell as the account
that runs it. Reports about authentication boundaries, request validation,
terminal proxying, command execution, local-user isolation, or unsafe installer
behavior are security reports.

## Supported versions

Security fixes are made on the `main` branch and included in the next release.
Only the latest release and current `main` receive fixes.

## Report a vulnerability privately

Use **Security → Advisories → Report a vulnerability** in this repository when
private vulnerability reporting is available. Include the affected version or
commit, prerequisites, impact, and the smallest reproduction you can provide.

If that button is unavailable, open a public issue that asks the maintainer to
provide a private reporting channel. Include no technical details there. Do not
put exploit details, credentials, private URLs, logs, or screenshots in a
public issue.

The maintainer aims to acknowledge a report within seven days and will
coordinate validation, a fix, and disclosure timing with you. Please allow a
reasonable remediation period before public disclosure.

## Operational incidents

If you believe a deployed serverjack instance is exposed, stop its user units
and remove its `tailscale serve` or reverse-proxy route first. Rotate any
credentials that appeared in terminal history or logs. Then report the defect
privately with sensitive values removed.
