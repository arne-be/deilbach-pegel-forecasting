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
