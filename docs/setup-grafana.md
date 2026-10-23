# Grafana setup

Grafana Cloud shows every time series in the prod database. The dashboards are JSON files in `grafana/dashboards/`; CI puts them into Grafana on merge to `main` (`infra/prod/grafana.tf`). The reasons are in [decision 0007](decisions/0007-grafana-dashboards.md).

These steps are done by hand once, in this order.

## 1. Stack

Sign up at grafana.com on the free plan and create a stack in an EU region. Note its URL, e.g. `https://<stack>.grafana.net`.

## 2. Service account for OpenTofu

In Grafana, under Administration → Users and access → Service accounts, create a service account `tofu` with the role **Admin** and add a token without expiry. Copy the token.

Editor isn't enough: in Grafana 13 an Editor service account only reaches the folders it's given, and asking for a folder that doesn't exist yet returns 403 instead of 404, so OpenTofu can't create the folder. The stack holds only this project, so Admin costs little.

## 3. Database role

Create `pegel_grafana` on both Neon branches, `prod` and `dev`, as in [setup-neon.md](setup-neon.md) step 3. Each branch gets its own password.

## 4. Token secret and CI roles

`infra/bootstrap/` creates the secret `deilbach-pegel/grafana-token` and lets the two CI roles read it. Apply it by hand ([infra/bootstrap/README.md](../infra/bootstrap/README.md)), then put the token in from the clipboard:

```
tmp=$(mktemp)
pbpaste > "$tmp"
aws secretsmanager put-secret-value --secret-id deilbach-pegel/grafana-token --secret-string "file://$tmp"
rm "$tmp"
pbcopy </dev/null
```

## 5. Data source

In Grafana, under Connections → Data sources, add a **PostgreSQL** data source named `deilbach-pegel` (the alert rule looks it up by that name):

- **Host:** the pooled host of the Neon `prod` branch (it contains `-pooler`), port `5432`
- **Database:** `pegel`
- **User:** `pegel_grafana`, with its `prod` password
- **TLS/SSL mode:** `require`
- **Max open connections:** `2`, **max idle:** `0`, **max lifetime:** `60` seconds, so no idle connection keeps Neon awake

Save & test. The password lives only in Grafana. The dashboards find the data source by type, so delete any other PostgreSQL data source: the dashboards might pick that one instead.

## 6. Stack URL for CI

```
gh variable set GRAFANA_URL --body https://<stack>.grafana.net
```

After that, `tofu plan` in pull requests and `tofu apply` on `main` manage the folder **Deilbach Pegel** and its dashboards.

## Changing a dashboard

Edit it in the Grafana UI until it looks right, then Export → Export as JSON (with "Export for sharing externally" off), save it over the file in `grafana/dashboards/`, remove the `id` field and open a pull request. Edits that only live in the UI are overwritten on the next deploy.

Keep auto-refresh off and don't add alert rules beyond the freshness rule below: every query wakes Neon, and the free plan has 100 CU-hours a month. Aggregate with `$__timeGroupAlias(valid_at, $__interval)` and filter with `$__timeFilter(valid_at)`, so a panel never loads raw rows for years.

## Freshness alerts

`infra/prod/alerts.tf` sets up one Grafana alert rule, "Data stale". It checks the newest value of each series in `freshness.alert_max_age_minutes` (`config/pegel.json`) once an hour, plus the newest forecast (key `forecast`). One email goes to the `BUDGET_EMAIL` address when a series goes stale, a "resolved" one when it's back, and a reminder every 24 hours while it stays stale. A failing query (e.g. Neon unreachable) also alerts. Grafana runs it at its own minute of the hour, not with the hourly job, so it wakes Neon once more per hour: about 15 CU-hours a month.

To change a limit or add a series, edit the config and merge. To try the rule before a merge, POST its queries to `/api/v1/eval` with the tofu token.
