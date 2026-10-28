# Freshness alerts: Grafana emails when a source stops delivering, even if the hourly job
# itself succeeds (a source that only logs warnings, as DWD's format change on 2026-10-20 did).
# The limits per series are in config/pegel.json (freshness.alert_max_age_minutes).

locals {
  alert_max_age_minutes = jsondecode(file("${path.module}/../../config/pegel.json")).freshness.alert_max_age_minutes
  alert_limits_sql = join(", ", [
    for item, minutes in local.alert_max_age_minutes : "('${item}', ${minutes})"
  ])
  # The newest value of each series, or the newest forecast for the item "forecast". Missing
  # for a week counts as very old, so a series that vanished still alerts.
  alert_age_sql   = <<-SQL
    WITH limits (item, max_age_minutes) AS (VALUES ${local.alert_limits_sql}),
    newest (item, newest_at) AS (
      SELECT series_id, max(valid_at) FROM observations
      WHERE series_id IN (SELECT item FROM limits) AND valid_at > now() - interval '7 days'
      GROUP BY series_id
      UNION ALL
      SELECT series_id, max(run_at) FROM input_forecasts
      WHERE series_id IN (SELECT item FROM limits) AND run_at > now() - interval '7 days'
      GROUP BY series_id
      UNION ALL
      SELECT 'forecast', max(issued_at) FROM forecasts WHERE issued_at > now() - interval '7 days'
    )
    SELECT limits.item, coalesce(extract(epoch FROM now() - newest.newest_at) / 60, 1e6) AS age_minutes
    FROM limits LEFT JOIN newest USING (item)
  SQL
  alert_limit_sql = "SELECT item, max_age_minutes FROM (VALUES ${local.alert_limits_sql}) AS limits (item, max_age_minutes)"
}

# Made by hand with the read-only role pegel_grafana (docs/setup-grafana.md).
data "grafana_data_source" "pegel" {
  name = "deilbach-pegel"
}

resource "grafana_contact_point" "email" {
  name = "deilbach-pegel email"

  email {
    # The owner's address, kept out of the public repo like the budget alerts' (GitHub variable).
    addresses    = [var.budget_email]
    single_email = true
  }

  # Starts the triage workflow, which emails a diagnosis through SNS (docs/decisions/0010).
  webhook {
    url                       = "https://api.github.com/repos/arne-be/deilbach-pegel-prediction/actions/workflows/alert-triage.yml/dispatches"
    authorization_scheme      = "Bearer"
    authorization_credentials = data.aws_secretsmanager_secret_version.github_dispatch_token.secret_string
    headers = {
      Accept                 = "application/vnd.github+json"
      "X-GitHub-Api-Version" = "2022-11-28"
    }
    disable_resolve_message = true

    # GitHub's dispatch body. Hand-built JSON instead of coll.Dict/data.ToJSON, which Grafana
    # Cloud doesn't list as generally available; the regex keeps each value JSON-safe and
    # inside the workflow's own check. Alerts without an item (DatasourceError) send their name.
    payload {
      template = <<-EOT
        {"ref":"main","inputs":{"items":"{{ range $i, $alert := .Alerts.Firing }}{{ if $i }},{{ end }}{{ reReplaceAll "[^A-Za-z0-9_:.-]" "" (or $alert.Labels.item $alert.Labels.alertname) }}{{ end }}"}}
      EOT
    }
  }
}

# Where the triage workflow sends its diagnosis.
resource "aws_sns_topic" "alert_triage" {
  name = "deilbach-pegel-alert-triage"
}

# Email subscriptions stay pending until the link in AWS's confirmation email is clicked.
resource "aws_sns_topic_subscription" "alert_triage_email" {
  topic_arn = aws_sns_topic.alert_triage.arn
  protocol  = "email"
  endpoint  = var.budget_email
}

# Fine-grained GitHub token (Actions read/write on this repo only), put in by hand
# (docs/setup-grafana.md). The secret is created in infra/bootstrap/; plans fail until it has a value.
# shortcut: the token lands in the prod state (private S3), because the webhook has no write-only
# field in grafana provider 4.46.0; switch to an ephemeral resource once it has one.
data "aws_secretsmanager_secret_version" "github_dispatch_token" {
  secret_id = "deilbach-pegel/github-dispatch-token"
}

resource "grafana_rule_group" "freshness" {
  name       = "freshness"
  folder_uid = grafana_folder.pegel.uid
  # Hourly, like the data: every evaluation wakes the Neon compute, which costs compute hours.
  interval_seconds = 3600

  rule {
    name      = "Data stale"
    condition = "C"
    for       = "0s"
    # A failing query (e.g. Neon down) and no rows both alert: either way nobody sees fresh data.
    no_data_state  = "Alerting"
    exec_err_state = "Error"

    annotations = {
      summary = "{{ $labels.item }}: newest value is {{ humanize $values.A.Value }} min old, limit {{ $values.B.Value }} min"
    }

    notification_settings {
      contact_point   = grafana_contact_point.email.name
      group_by        = ["alertname", "grafana_folder"]
      repeat_interval = "24h"
    }

    data {
      ref_id         = "A"
      datasource_uid = data.grafana_data_source.pegel.uid
      relative_time_range {
        from = 3600
        to   = 0
      }
      model = jsonencode({
        refId      = "A"
        format     = "table"
        rawQuery   = true
        editorMode = "code"
        rawSql     = local.alert_age_sql
      })
    }

    data {
      ref_id         = "B"
      datasource_uid = data.grafana_data_source.pegel.uid
      relative_time_range {
        from = 3600
        to   = 0
      }
      model = jsonencode({
        refId      = "B"
        format     = "table"
        rawQuery   = true
        editorMode = "code"
        rawSql     = local.alert_limit_sql
      })
    }

    data {
      ref_id         = "C"
      datasource_uid = "__expr__"
      relative_time_range {
        from = 0
        to   = 0
      }
      model = jsonencode({
        refId      = "C"
        type       = "math"
        expression = "$A > $B"
      })
    }
  }
}
