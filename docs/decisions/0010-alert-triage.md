# 0010 · Alert triage with Claude

- **Status:** accepted
- **Date:** 2026-10-28

## Decisions

**A diagnosis follows each "Data stale" alert.** The alert says what is stale, not why. Finding out means reading the Lambda log, the database and the source portal by hand. Claude does that first and emails a short diagnosis: what is stale, the likely cause, upstream or ours, what to do.

**GitHub Actions runs it, started by Grafana's webhook.** The contact point gets a second integration that calls GitHub's `workflow_dispatch` with the stale items. Actions has the repo checked out, OIDC roles into AWS and costs nothing. A scheduled Claude routine would run whether or not anything is wrong and would need its own access to AWS; this runs only when an alert fires.

**Claude on Amazon Bedrock, through the GitHub OIDC role.** No Anthropic API key to store or rotate; billing and access stay in the AWS account. The role `deilbach-pegel-github-triage` may only call the Sonnet EU inference profile, read the hourly Lambda log and the read-only API database URL, and publish to one SNS topic.

**Evidence first, then a read-only Claude.** A plain shell step collects the evidence into a file. Claude gets only `Read`, `Grep` and `Glob`: no shell, no web, and the database URL isn't in its environment. Logs and portal answers are untrusted data, so the worst a prompt injection can do is change the email's text.

**The email goes through SNS.** One topic and an email subscription, no domain to verify as SES would need.

**Repeats follow Grafana.** One run per notification, so a stale series gets a diagnosis when it fires and with each daily reminder. No extra dedupe.

## Accepted

- **The GitHub token is in the prod state.** The webhook's credentials have no write-only field in grafana provider 4.46.0, so the token is read with a normal data source and stored in state (private, encrypted S3 bucket). Its Actions read/write scope can't be narrowed further: besides starting workflows it can rerun, cancel and delete runs in this repo, including rerunning an old `infra` deploy (prod rolls back to that commit) or rerunning this workflow with debug logging. If it leaks, revoke it on GitHub. A required reviewer on the deploy job would close the rollback path. Move it to an ephemeral value once the provider allows it.
- **Actions logs are public.** The workflow never prints evidence, logs or Claude's output, and Claude's full-output option stays off. Rerunning with debug logging would print them, so don't.
- The token expires and must be renewed by hand. When it runs out, the Grafana email still arrives, only without a diagnosis.
- Each alert costs one Bedrock call of up to 15 turns, a few cents.
