---
description: Infrastructure, security and monitoring standards
---

# Operations

- **Infrastructure as code.** No manual changes in the AWS console that aren't also in code.
- **Least privilege.** Each component gets only the permissions it needs; read-only access to source systems.
- Secrets come from environment variables or AWS Secrets Manager, never from the repo.
- **Structured logging** with timestamps and context (job, time window, station). Never log secrets or personal data.
- **Monitor freshness.** Alert when observations or forecasts are older than expected, not only when a job crashes.
- Keep running costs small; prefer scheduled or serverless jobs over always-on servers where it fits.
- **Local secrets** live in `.env.local` (gitignored, mode 600), and so does the source DB host, because the repo is public. Other connection settings go in `.env`. Certificates and keys stay outside the repo in `~/.config/deilbach-pegel/`. `.env.example` lists every variable without values.
- **Secret scanning:** gitleaks runs as a pre-commit hook (`.githooks/`) and in CI. Never bypass it with `--no-verify`.
- **Never put credentials in URLs.** InfluxDB 1.x accepts `u=`/`p=` query parameters; use HTTP basic auth instead, so credentials can't leak into logs, tracebacks or proxy logs. Don't log full request URLs or headers.
- **Commands that output secrets write them straight into their destination**, never to the terminal or a chat. For example `neon cs` prints a full connection string with password: capture it in a variable and write it into `.env.local`. Checks print the role and host only, never the URL.
- **Source DB access is read-only by design:** use an InfluxDB user with only `READ` on `level`.
- **Check the first prod run after a merge that changes the hourly job.** Steps that fail are logged and skipped, so a green run can still miss data. Read the Lambda log (`/aws/lambda/deilbach-pegel-run-hourly`) and check that each new series got rows. A timeout that never shows up locally can show up from Lambda.
