# 0004 · Environments, deployment and CI access

- **Status:** accepted
- **Date:** 2026-10-12

## Context

One person runs the system. The repo is public, so anyone can open a pull request.

## Decisions

### Local and prod only

There is no staging stack on AWS. Local development uses a Neon `dev` branch: a copy of prod with its own passwords. Tests, `tofu plan` in every pull request and deploys only from `main` replace a staging environment. The OpenTofu code takes an environment name, so staging can be added later.

### Auto-deploy on merge to main

GitHub Actions runs checks and `tofu plan` on every pull request. A merge to `main` builds, applies and deploys without a manual approval step. The pull request with its plan is the approval.

### Two CI roles via OIDC

CI logs in with GitHub's OIDC, so there are no stored AWS keys. The plan role is read only and only trusted for pull requests from this repo. The deploy role is only trusted on `main` and limited to our own resources. A pull request from a fork gets no AWS access at all.

### Public repo, locked down

The repo stays public. Workflows from outside contributors need approval. The client's database host is kept out of the repo. It was already in the history; we don't rewrite it, because the host alone gives no access without the client certificate and credentials.

### State and bootstrap

The OpenTofu state is in S3 with OpenTofu's built-in locking. The state bucket and the OIDC roles come from `infra/bootstrap/`, applied by hand once.

### Laptop runs against prod

Two things run from a laptop on purpose:
- **The first backfill.** It uses the prod connection string as a temporary environment variable, only for that run.
- **Training experiments.** They use a fresh `dev` copy of prod, or prod's read-only role if needed.

## Rejected

- **A staging stack on AWS.** Twice the setup for one person.
- **A manual approval before deploy.** Only adds clicks.
- **One CI role for everything.** A pull request from anyone could change the AWS account.
- **A private repo.** Branch protection on a private personal repo needs GitHub Pro. A public repo also serves as portfolio.
- **Rewriting history to remove the host.** Breaks open pull requests, and GitHub keeps old commits reachable anyway.

## Consequences

- Mistakes reach prod faster, so checks in CI matter.
- The deploy role's permissions are written by hand and widened when a deploy fails on a missing permission.
