# Permissions boundary for every role infra/prod creates. The deploy role may only
# create or change deilbach-pegel* roles that carry it (roles.tf), so it can't make
# itself an admin role and run a Lambda with it. A role's rights are its own policies
# cut down to what this allows. Widen it here when a workload needs more.

data "aws_iam_policy_document" "workload_boundary" {
  statement {
    sid     = "Logs"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:${local.region_account}:log-group:/aws/lambda/deilbach-pegel*",
      "arn:aws:logs:${local.region_account}:log-group:/aws/lambda/deilbach-pegel*:*",
    ]
  }

  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${local.region_account}:secret:deilbach-pegel/*"]
  }

  # The owner connection string, the Grafana token and the GitHub token are for CI only.
  statement {
    sid     = "NoCiSecrets"
    effect  = "Deny"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      local.migrate_secret_arn,
      aws_secretsmanager_secret.grafana_token.arn,
      aws_secretsmanager_secret.github_dispatch_token.arn,
    ]
  }

  statement {
    sid       = "DataBucket"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::deilbach-pegel-data-*", "arn:aws:s3:::deilbach-pegel-data-*/*"]
  }

  # The scheduler role starts the Lambdas.
  statement {
    sid       = "InvokeLambdas"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${local.region_account}:function:deilbach-pegel*"]
  }
}

# infra/prod builds the ARN from this name (local.workload_boundary_arn there).
resource "aws_iam_policy" "workload_boundary" {
  name   = "deilbach-pegel-workload-boundary"
  policy = data.aws_iam_policy_document.workload_boundary.json
}
