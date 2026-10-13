# Grafana Cloud folder and dashboards. The dashboards are the JSON files in
# grafana/dashboards/. The Postgres data source is made by hand, so its password
# never passes through code or state (docs/setup-grafana.md); the dashboards pick
# it up through a hidden datasource variable.

variable "grafana_url" {
  description = "URL of the Grafana Cloud stack, e.g. https://<stack>.grafana.net"
  type        = string
}

# Ephemeral, so the token stays out of the plan and the state. The secret is
# created in infra/bootstrap/.
ephemeral "aws_secretsmanager_secret_version" "grafana_token" {
  secret_id = "deilbach-pegel/grafana-token"
}

provider "grafana" {
  url  = var.grafana_url
  auth = ephemeral.aws_secretsmanager_secret_version.grafana_token.secret_string
}

resource "grafana_folder" "pegel" {
  uid   = "deilbach-pegel"
  title = "Deilbach Pegel"
}

resource "grafana_dashboard" "this" {
  for_each = fileset("${path.module}/../../grafana/dashboards", "*.json")

  folder      = grafana_folder.pegel.uid
  config_json = file("${path.module}/../../grafana/dashboards/${each.value}")
  overwrite   = true
}
