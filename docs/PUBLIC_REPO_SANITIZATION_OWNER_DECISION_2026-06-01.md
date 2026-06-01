# Selva Office Public Repo Sanitization Owner Decision

Date: 2026-06-01
Current status: blocked, not sanitized

## Evidence summary

- Current-tree exact credential-signature paths: 0
- Git-history matched paths: 3
- GitHub Actions artifacts reported: 1442
- Releases page count: 0

## Required owner decisions

- Choose `history_rewrite` or `risk_acceptance_plus_revocation` for history matches.
- Choose `artifact_body_review`, `artifact_retention_cleanup`, or `artifact_risk_acceptance` for public artifacts.
- Confirm no GitHub admin token, webhook secret, campaign data, customer lead data, internal prompt, or privileged campaign procedure exists in public source/history/artifacts.
- Approve or reject whether Selva Office can produce `PUBLIC_GITHUB_REPO_SANITIZED` Tulana evidence.

## Recommended decision

Keep status blocked until webhook/GitHub fixture history and public CI artifacts receive owner disposition.

## Artifact retention evidence update

Current-tree workflow audit found zero checked workflows using `actions/upload-artifact`, so no current workflow retention edit was applied in this pass. Existing GitHub artifact volume remains launch-blocking.

Owner still needs to choose artifact body review, artifact retention cleanup, or explicit time-bounded artifact risk acceptance.

## Full artifact metadata update

- Total artifacts: 1,442
- Active artifacts: 1,428
- Expired artifacts: 14
- Total artifact bytes: 63,267,522
- Risk-name artifacts: 97
- Active risk-name artifacts: 97
- Risk-name artifact bytes: 2,442,643

Owner review should start with active risk-name artifacts tied to webhook, report, log, campaign, or agent workflows.
