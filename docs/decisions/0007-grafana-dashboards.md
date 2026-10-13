# 0007 · Grafana dashboards as code

- **Status:** accepted
- **Date:** 2026-10-13

## Decisions

**Grafana Cloud, free plan**, reading the Neon `prod` branch directly with its PostgreSQL data source. It's for looking at the data while we build the model, not for the public. No server of our own and no exporter.

**Dashboards are JSON files in `grafana/dashboards/`**, put into Grafana by the `grafana/grafana` OpenTofu provider on merge to `main`. A coding agent can write and change them in a pull request, and `tofu plan` shows the change before it lands.

**The data source is made by hand.** Its password goes from the password manager straight into Grafana and never passes through code, state or CI. The dashboards find it through a hidden datasource variable, so they don't need its uid.

**The Grafana token lives in Secrets Manager** (`deilbach-pegel/grafana-token`). The provider needs it for `tofu plan` too, so the plan and deploy roles may read this one secret value and no other. The secret is created in `infra/bootstrap/`, because `infra/prod/` can't plan before it has a value. OpenTofu reads it as an ephemeral value, so it stays out of the plan and the state.

**Its own database role**, `pegel_grafana`, with `SELECT` on the data tables only, a connection limit of 3 and a 15 second statement timeout.

**No auto-refresh and no alert rules.** Every query wakes the Neon compute, and the free plan has 100 CU-hours a month. The freshness table on the dashboard is something to look at, not an alert; [0006](0006-operations.md) still holds.

## Accepted

- The dashboard queries name a few things the config also knows, such as the variables `level` and `rain`. Station IDs and thresholds stay out: the forecast panel takes its stations from the `forecasts` table.
- Anyone who can push a branch to this repo could print the Grafana token through `tofu plan`. Today that's one person.

## Rejected

- **Local Grafana in Docker.** No account needed, but only reachable from one laptop.
- **Amazon Managed Grafana.** About $9 per editor a month plus IAM Identity Center.
- **The token as a GitHub secret.** Secrets stay in one place, Secrets Manager.
- **The data source in OpenTofu.** Its password would end up in the state.
