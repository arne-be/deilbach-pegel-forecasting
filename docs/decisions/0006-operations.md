# 0006 · Logging, costs and freshness

- **Status:** accepted
- **Date:** 2026-10-12

## Decisions

**Logs** are JSON lines on stdout. CloudWatch keeps them for 30 days; the default is forever. CloudFront access logs stay off: the Lambda logs are enough for debugging, and access logs would contain IP addresses.

**Costs** are guarded by one AWS Budget at €10 a month, with an email at 80 % of actual or 100 % of forecast spend. It's the only alert in the system. Limits cap the damage on their own:
- reserved concurrency of 5 for the API Lambda and 1 for each job Lambda
- tight timeouts per job

We don't use WAF; its base fee would be half our budget.

**Freshness** is checked in the browser. The page compares the timestamps in each response with the current time, using thresholds from `config/pegel.json`. The API adds a `stale` flag with the same rule for other users. There's no server-side alerting; the page is the warning.

## Rejected

- **Alerts for late data or failed jobs.** One person runs the system, and the page shows late data clearly. We break our "monitor freshness" rule on purpose here; a free CloudWatch alarm can be added any time.
- **AWS WAF.** Too expensive for what caching and concurrency limits already cover.
- **Trusting the API's `stale` flag alone.** A cached response can be outdated, so the browser checks too.
