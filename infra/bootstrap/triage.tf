# Role for .github/workflows/alert-triage.yml: reads the evidence for a stale-data
# alert, asks Claude (Anthropic API) for a diagnosis and emails it via SNS. Nothing else:
# no ReadOnlyAccess, because the workflow's output goes by email and its logs are public.

resource "aws_iam_role" "github_triage" {
  name               = "deilbach-pegel-github-triage"
  assume_role_policy = data.aws_iam_policy_document.github_trust["triage"].json
}

data "aws_iam_policy_document" "github_triage" {
  statement {
    sid       = "AnthropicApiKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.anthropic_api_key.arn]
  }

  statement {
    sid     = "HourlyLog"
    actions = ["logs:FilterLogEvents", "logs:GetLogEvents", "logs:DescribeLogStreams"]
    resources = [
      "arn:aws:logs:${local.region_account}:log-group:/aws/lambda/deilbach-pegel-run-hourly",
      "arn:aws:logs:${local.region_account}:log-group:/aws/lambda/deilbach-pegel-run-hourly:*",
    ]
  }

  # The read-only API connection string, for the newest values per series.
  statement {
    sid       = "ApiDatabaseUrl"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${local.region_account}:secret:deilbach-pegel/api-database-url-??????"]
  }

  # The topic is created in infra/prod.
  statement {
    sid       = "SendDiagnosis"
    actions   = ["sns:Publish"]
    resources = ["arn:aws:sns:${local.region_account}:deilbach-pegel-alert-triage"]
  }
}

resource "aws_iam_role_policy" "github_triage" {
  name   = "deilbach-pegel-github-triage"
  role   = aws_iam_role.github_triage.id
  policy = data.aws_iam_policy_document.github_triage.json
}
