# Role for .github/workflows/alert-triage.yml: reads the evidence for a stale-data
# alert, asks Claude on Bedrock for a diagnosis and emails it via SNS. Nothing else:
# no ReadOnlyAccess, because the workflow's output goes by email and its logs are public.

locals {
  # The workflow passes the profile ID (eu.<model>) to Bedrock. The profile routes each
  # call to one of the EU regions, so the model ARN allows any of them.
  triage_model = "anthropic.claude-sonnet-5-5"
}

resource "aws_iam_role" "github_triage" {
  name               = "deilbach-pegel-github-triage"
  assume_role_policy = data.aws_iam_policy_document.github_trust["triage"].json
}

data "aws_iam_policy_document" "github_triage" {
  statement {
    sid     = "Bedrock"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:${local.region_account}:inference-profile/eu.${local.triage_model}",
      "arn:aws:bedrock:eu-*::foundation-model/${local.triage_model}",
    ]
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
