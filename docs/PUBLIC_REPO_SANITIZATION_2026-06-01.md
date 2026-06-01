# Selva Office Public Repo Sanitization Contract

Date: 2026-06-01
Status: launch-blocking for campaign, agent, back-office, and automation readiness

## Position

Selva Office can operate campaign and back-office workflows. Public repo sanitization must ensure examples, tests, tools, agent prompts, and operational docs do not expose credentials or overstate autonomous campaign capability.

## Current remediation posture

- Scanner-valid dummy credential strings in the identified GitHub admin and webhook tests were normalized to non-credential-shaped placeholders.
- No repo-level pass is granted until current-tree scan, history scan, public artifact review, and owner approval are recorded in Tulana.

## Launch-blocking checks

A Selva-linked platform/SKU cannot pass Product/Offer GA public-repo sanitization until evidence confirms:

- GitHub, webhook, campaign, CRM, and agent fixtures are synthetic.
- Public docs do not expose operator-only workflows, internal prompts, customer data, or privileged campaign procedures.
- Public claims around agent autonomy, outreach, campaign import, and fulfillment are bounded by what production can execute safely.
- Required AI disclosure and human-approval requirements are visible where relevant.

## Required Tulana evidence

Use `PUBLIC_GITHUB_REPO_SANITIZED` evidence attached to `P4`, `P8`, and `P9`; attach to `P0` when public Selva docs or agent claims are used as buyer-facing proof.
