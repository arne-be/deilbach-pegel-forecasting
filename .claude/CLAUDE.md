## Project
deilbach-pegel-prediction — hourly 48-hour water level forecast for the Deilbach gauge at Kupferdreh, with flood categories and uncertainty ranges, shown on a public German-language web page. See `README.md` for categories and plan.

## Stack
- Jobs and API: Python, one Dockerfile with a jobs image and an API image, run as AWS Lambda (eu-central-1), scheduled by EventBridge. The API is FastAPI behind the AWS Lambda Web Adapter.
- Database: Neon Postgres (free plan, Frankfurt). Files, models and backups: S3.
- Website: Astro + React + TypeScript, static on S3 + CloudFront.
- Infrastructure: OpenTofu.
- Details in `docs/architecture.md`, reasons in `docs/decisions/`. Ask before adding major dependencies or infrastructure.

## Layout and commands
The repo layout and all commands live in `AGENTS.md`, shared with other coding agents.

@../AGENTS.md

## Verification
After every change, run in this order:
1. Type check — fix type errors
2. Tests — fix failing tests
3. Lint — fix lint errors

## Workflow
- Plan first for non-trivial tasks (3+ steps or design decisions). If something goes sideways, stop and re-plan.
- Never call a task done without proving it works: run tests, check output.
- Keep changes minimal: touch only what the task needs. Find root causes, no temporary fixes.
- After a correction from the user, add a rule here or in `.claude/rules/` so it doesn't happen again.

## Project rules
- **Source systems are read only.** Never write to the client's database or any upstream API.
- **Negative levels are real.** Values down to −0.25 m are valid; don't clean them away.
- **Never present stale data as current.** Every forecast carries its issue time and the time of the newest observation it used.
- **Time:** store and compute in UTC; display in Europe/Berlin.
- **Units:** metres relative to the local zero point. German formatting (`0,68 m`) only in the UI.
- **Language:** website in German; code, comments, docs and commits in English.
- Category thresholds, horizons and station IDs live in one config place, never hard-coded in several files.

## Don't
- Don't work or commit on `main` — always use a worktree with a branch from the newest `origin/main`, then open a PR (see `.claude/rules/git-workflow.md`).
- Don't put secrets in the repo — use environment variables or AWS Secrets Manager.
- Don't evaluate models with random splits — split by time.
