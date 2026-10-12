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
- **Local secrets** live in `.env.local` (gitignored, mode 600); connection settings in `.env`. Certificates and keys stay outside the repo in `~/.config/deilbach-pegel/`. `.env.example` lists every variable without values.
- **Secret scanning:** gitleaks runs as a pre-commit hook (`.githooks/`) and in CI. Never bypass it with `--no-verify`.
- **Never put credentials in URLs.** InfluxDB 1.x accepts `u=`/`p=` query parameters; use HTTP basic auth instead, so credentials can't leak into logs, tracebacks or proxy logs. Don't log full request URLs or headers.
- **Source DB access is read-only by design:** use an InfluxDB user with only `READ` on `level`.
