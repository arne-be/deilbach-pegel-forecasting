# Everything on AWS except the state bucket and the CI roles (those are in infra/bootstrap/).
# Applied only by GitHub Actions on merge to main.

terraform {
  required_version = "1.13.1"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.66.0"
    }
  }

  # The bucket is passed at init: tofu init -backend-config="bucket=$TF_STATE_BUCKET"
  backend "s3" {
    key          = "prod/terraform.tfstate"
    region       = "eu-central-1"
    use_lockfile = true
  }
}

provider "aws" {
  region = "eu-central-1"

  default_tags {
    tags = {
      project = "deilbach-pegel"
    }
  }
}

variable "jobs_image_tag" {
  description = "Tag of the jobs image in ECR, the git SHA it was built from"
  type        = string
}

variable "budget_email" {
  description = "Where the budget alerts go"
  type        = string
}

data "aws_caller_identity" "current" {}

resource "aws_ecr_repository" "jobs" {
  name = "deilbach-pegel-jobs"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "jobs" {
  repository = aws_ecr_repository.jobs.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# Raw files, models, backups and the published JSON files, once those jobs exist.
resource "aws_s3_bucket" "data" {
  # Bucket names are global, so the account ID keeps this one unique.
  bucket = "deilbach-pegel-data-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Values are put in by hand (docs/setup-aws.md), so they never pass through code or state.
resource "aws_secretsmanager_secret" "influx" {
  name        = "deilbach-pegel/influx"
  description = "JSON with INFLUX_URL, INFLUX_USERNAME, INFLUX_PASSWORD"
}

resource "aws_secretsmanager_secret" "influx_client_cert" {
  name        = "deilbach-pegel/influx-client-cert"
  description = "Client certificate for the source database, PEM"
}

resource "aws_secretsmanager_secret" "influx_client_key" {
  name        = "deilbach-pegel/influx-client-key"
  description = "Client key for the source database, PEM"
}

resource "aws_secretsmanager_secret" "jobs_database_url" {
  name        = "deilbach-pegel/jobs-database-url"
  description = "Neon prod pooled connection string, role pegel_jobs"
}

resource "aws_budgets_budget" "monthly" {
  name         = "deilbach-pegel-monthly"
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
