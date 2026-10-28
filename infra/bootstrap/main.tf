# Applied by hand once with admin credentials. Creates the state bucket for
# infra/prod and the two GitHub OIDC roles CI uses. State stays local here,
# because this config creates the bucket a remote backend would need.

terraform {
  required_version = "1.13.1"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.68.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"

  default_tags {
    tags = {
      project    = "deilbach-pegel"
      managed_by = "opentofu/infra/bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  # GitHub's immutable OIDC subject: owner and repo names with their IDs, so a renamed or
  # recreated repo can't take over these roles. From
  # `gh api repos/arne-be/deilbach-pegel-prediction/actions/oidc/customization/sub`.
  github_subject_prefix = "repo:arne-be@42965806/deilbach-pegel-prediction@1415234162"
}

# --- State bucket for infra/prod (OpenTofu native S3 locking, no DynamoDB) ---

resource "aws_s3_bucket" "tofu_state" {
  bucket = "deilbach-pegel-tofu-state-${local.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tofu_state" {
  bucket = aws_s3_bucket.tofu_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tofu_state" {
  bucket = aws_s3_bucket.tofu_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tofu_state" {
  bucket = aws_s3_bucket.tofu_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "tofu_state_tls_only" {
  statement {
    sid     = "DenyNonTls"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.tofu_state.arn,
      "${aws_s3_bucket.tofu_state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tofu_state" {
  bucket = aws_s3_bucket.tofu_state.id
  policy = data.aws_iam_policy_document.tofu_state_tls_only.json

  # S3 rejects a bucket policy while the public access block is still being applied.
  depends_on = [aws_s3_bucket_public_access_block.tofu_state]
}

# --- GitHub OIDC ---

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# --- Grafana token ---

# Service account token for Grafana Cloud, read by tofu plan and apply in infra/prod.
# Here and not in infra/prod, because the grafana provider needs the value before
# infra/prod can plan at all. The value is put in by hand (infra/bootstrap/README.md).
resource "aws_secretsmanager_secret" "grafana_token" {
  name        = "deilbach-pegel/grafana-token"
  description = "Grafana Cloud service account token (Editor), used by OpenTofu"
}

# Fine-grained GitHub token (Actions read and write, this repo only). Grafana's alert
# webhook uses it to start .github/workflows/alert-triage.yml. infra/prod reads it at
# plan time, like the Grafana token. The value is put in by hand (docs/setup-grafana.md).
resource "aws_secretsmanager_secret" "github_dispatch_token" {
  name        = "deilbach-pegel/github-dispatch-token"
  description = "GitHub token that starts the alert triage workflow, used by OpenTofu"
}
