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
      group_by        = ["alertname"]
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
