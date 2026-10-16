# The two CI roles. Plan: read only, pull requests from this repo. Deploy:
# manages deilbach-pegel* resources, only from main. Both can read the Grafana
# token and no other secret value, because tofu plan needs it for the dashboards.
# A fork's pull request gets no OIDC token from GitHub, and infra.yml skips the
# AWS steps for forks. The trust policy alone would let one in, so never run
# infra.yml on pull_request_target.

data "aws_iam_policy_document" "github_trust" {
  for_each = {
    plan   = "${local.github_subject_prefix}:pull_request"
    deploy = "${local.github_subject_prefix}:ref:refs/heads/main"
  }

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [each.value]
    }
  }
}

resource "aws_iam_role" "github_plan" {
  name               = "deilbach-pegel-github-plan"
  assume_role_policy = data.aws_iam_policy_document.github_trust["plan"].json
}

resource "aws_iam_role" "github_deploy" {
  name               = "deilbach-pegel-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_trust["deploy"].json
}

# Both roles run tofu plan, which needs to read every managed resource.
resource "aws_iam_role_policy_attachment" "read_only" {
  for_each = {
    plan   = aws_iam_role.github_plan.name
    deploy = aws_iam_role.github_deploy.name
  }

  role       = each.value
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# --- Plan role ---

data "aws_iam_policy_document" "github_plan" {
  statement {
    sid       = "StateLockFiles"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tofu_state.arn}/*.tflock"]
  }

  statement {
    sid       = "GrafanaToken"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.grafana_token.arn]
  }

  statement {
    sid           = "NoOtherSecretValues"
    effect        = "Deny"
    actions       = ["secretsmanager:GetSecretValue"]
    not_resources = [aws_secretsmanager_secret.grafana_token.arn]
  }
}

resource "aws_iam_role_policy" "github_plan" {
  name   = "deilbach-pegel-github-plan"
  role   = aws_iam_role.github_plan.id
  policy = data.aws_iam_policy_document.github_plan.json
}

# --- Deploy role ---

locals {
  region_account = "eu-central-1:${local.account_id}"
  # ?????? is the random suffix Secrets Manager adds; not *, so similarly named secrets don't match.
  migrate_secret_arn = "arn:aws:secretsmanager:${local.region_account}:secret:deilbach-pegel/migrate-database-url-??????"
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "Ecr"
    actions   = ["ecr:*"]
    resources = ["arn:aws:ecr:${local.region_account}:repository/deilbach-pegel*"]
  }

  statement {
    sid       = "Lambda"
    actions   = ["lambda:*"]
    resources = ["arn:aws:lambda:${local.region_account}:function:deilbach-pegel*"]
  }

  # Data and site buckets, plus the state bucket (deilbach-pegel-tofu-state-*).
  statement {
    sid     = "S3"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::deilbach-pegel*",
      "arn:aws:s3:::deilbach-pegel*/*",
    ]
  }

  statement {
    sid     = "Iam"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${local.account_id}:role/deilbach-pegel*",
      "arn:aws:iam::${local.account_id}:policy/deilbach-pegel*",
    ]
  }

  statement {
    sid     = "Scheduler"
    actions = ["scheduler:*"]
    resources = [
      "arn:aws:scheduler:${local.region_account}:schedule/*/deilbach-pegel*",
      "arn:aws:scheduler:${local.region_account}:schedule-group/deilbach-pegel*",
    ]
  }

  statement {
    sid = "SecretsWithoutValues"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:UpdateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:TagResource",
      "secretsmanager:UntagResource",
      "secretsmanager:GetResourcePolicy",
    ]
    resources = ["arn:aws:secretsmanager:${local.region_account}:secret:deilbach-pegel*"]
  }

  statement {
    sid     = "Logs"
    actions = ["logs:*"]
    resources = [
      "arn:aws:logs:${local.region_account}:log-group:/aws/lambda/deilbach-pegel*",
      "arn:aws:logs:${local.region_account}:log-group:deilbach-pegel*",
    ]
  }

  statement {
    sid       = "Budgets"
    actions   = ["budgets:*"]
    resources = ["arn:aws:budgets::${local.account_id}:budget/deilbach-pegel*"]
  }

  # The website certificate. CloudFront only takes certificates from us-east-1, and
  # RequestCertificate has no resource ARN to scope to.
  statement {
    sid       = "AcmRequest"
    actions   = ["acm:RequestCertificate"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["us-east-1"]
    }
  }

  statement {
    sid       = "Acm"
    actions   = ["acm:*"]
    resources = ["arn:aws:acm:us-east-1:${local.account_id}:certificate/*"]
  }

  # shortcut: CloudFront has few resource-level permissions; scope down if more distributions share this account.
  statement {
    sid       = "CloudFront"
    actions   = ["cloudfront:*"]
    resources = ["*"]
  }

  # Grafana reads its token; the deploy job migrates the prod database. ReadOnlyAccess has no secret values.
  statement {
    sid       = "ReadableSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.grafana_token.arn, local.migrate_secret_arn]
  }

  # An explicit deny beats any allow, so it has to leave out the secrets above.
  statement {
    sid           = "NoOtherSecretValues"
    effect        = "Deny"
    actions       = ["secretsmanager:GetSecretValue"]
    not_resources = [aws_secretsmanager_secret.grafana_token.arn, local.migrate_secret_arn]
  }

  # The CI roles must not be able to widen their own permissions or trust.
  statement {
    sid       = "NoChangesToCiRoles"
    effect    = "Deny"
    actions   = ["iam:*"]
    resources = ["arn:aws:iam::${local.account_id}:role/deilbach-pegel-github-*"]
  }

  # Without these, the deploy role could create an admin role and run a Lambda with it.
  # For an existing role, iam:PermissionsBoundary is the boundary it already has; for
  # CreateRole and PutRolePermissionsBoundary, the one in the request. Missing counts as not equal.
  statement {
    sid       = "RolesOnlyWithBoundary"
    effect    = "Deny"
    actions   = ["iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:PutRolePermissionsBoundary"]
    resources = ["arn:aws:iam::${local.account_id}:role/deilbach-pegel*"]

    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.workload_boundary.arn]
    }
  }

  statement {
    sid       = "KeepRoleBoundaries"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["arn:aws:iam::${local.account_id}:role/deilbach-pegel*"]
  }

  # The boundary policy matches the Iam allow above, so only reads stay open.
  statement {
    sid         = "KeepBoundaryPolicy"
    effect      = "Deny"
    not_actions = ["iam:Get*", "iam:List*"]
    resources   = [aws_iam_policy.workload_boundary.arn]
  }

  statement {
    sid       = "KeepStateBucket"
    effect    = "Deny"
    actions   = ["s3:DeleteBucket", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutBucketVersioning"]
    resources = [aws_s3_bucket.tofu_state.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deilbach-pegel-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
