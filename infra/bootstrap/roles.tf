# The two CI roles. Plan: read only, pull requests from this repo. Deploy:
# manages deilbach-pegel* resources, only from main. A fork's pull request
# gets no OIDC token for this repo's subject, so it gets no AWS access.

data "aws_iam_policy_document" "github_trust" {
  for_each = {
    plan   = "repo:${local.github_repo}:pull_request"
    deploy = "repo:${local.github_repo}:ref:refs/heads/main"
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
    sid       = "NoSecretValues"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["*"]
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

  # shortcut: CloudFront has few resource-level permissions; scope down if more distributions share this account.
  statement {
    sid       = "CloudFront"
    actions   = ["cloudfront:*"]
    resources = ["*"]
  }

  statement {
    sid       = "NoSecretValues"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["*"]
  }

  # The CI roles must not be able to widen their own permissions or trust.
  statement {
    sid       = "NoChangesToCiRoles"
    effect    = "Deny"
    actions   = ["iam:*"]
    resources = ["arn:aws:iam::${local.account_id}:role/deilbach-pegel-github-*"]
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
