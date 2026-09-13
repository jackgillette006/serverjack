# Maintainer notifications

GitHub is the durable attention queue for this repository. The repository owner
should keep **Watch → All activity** enabled and configure GitHub account email
or mobile notifications for participating and watching activity.

The `Maintainer attention` workflow adds `maintainer-attention` to new,
reopened, edited, or newly commented issues and pull requests, including new
reviews and commits. It opens one `ci-failed` issue when the latest default-
branch `CI` run fails, comments on later failures, and closes that issue when
the latest run recovers. A published release creates a `release-follow-up`
issue so post-release checks have an explicit owner and audit trail.

Security alerts stay in GitHub's private security UI. Enable Dependabot alerts,
secret scanning, push protection, code scanning where supported, and private
vulnerability reporting. Configure security-alert notifications in the owner's
GitHub notification settings. The attention workflow deliberately does not copy
private alert details into public issues or logs.

Dependabot checks pinned GitHub Actions weekly through `.github/dependabot.yml`.
Its update pull requests enter the same labeled review queue.

## Triage routine

1. Filter open issues and pull requests by `maintainer-attention`.
2. Reproduce bug reports from a clean checkout and remove the label when the
   report has an owner or disposition.
3. Treat pull-request content as untrusted. Review the diff before running it
   and never add secrets to a pull-request-triggered job.
4. Resolve an open `ci-failed` issue only after a successful `CI` run; the
   workflow normally closes it automatically.
5. For each `release-follow-up` issue, verify install and upgrade instructions,
   inspect the release assets, and close it when the release is healthy.
6. Review the repository Security tab separately; never paste private alert
   details into a public issue.
