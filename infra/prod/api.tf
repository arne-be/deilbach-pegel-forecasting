# The public API: a Lambda from the API image, reached only through CloudFront on /api/*.
# CloudFront signs its requests (origin access control), so the function URL accepts nothing else.

locals {
  api_name = "deilbach-pegel-api"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.api_name}"
  retention_in_days = 30
}

resource "aws_iam_role" "api" {
  name                 = local.api_name
  permissions_boundary = local.workload_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.api.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.api_database_url.arn
      },
      {
        # Only the two files the hourly run publishes for it (src/pegel/adapters/api_files.py).
        Effect = "Allow"
        Action = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.data.arn}/api/forecast.json",
          "${aws_s3_bucket.data.arn}/api/recent.json",
        ]
      },
    ]
  })
}

resource "aws_lambda_function" "api" {
  function_name = local.api_name
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  # Same repository as the jobs image, tagged api-<sha> by the deploy job.
  image_uri     = "${aws_ecr_repository.jobs.repository_url}:api-${var.jobs_image_tag}"
  architectures = ["arm64"]
  # Enough for Neon waking from suspend plus the query.
  timeout     = 30
  memory_size = 512
  # shortcut: no reserved concurrency of 5, because AWS refuses any reservation while the
  # account limit is 10 (as in hourly.tf). Add it once the Lambda concurrency quota is raised.

  environment {
    variables = {
      API_DATABASE_URL_SECRET_NAME = aws_secretsmanager_secret.api_database_url.name
      API_FILES_BUCKET             = aws_s3_bucket.data.bucket
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "AWS_IAM"
}

# Function URLs created since October 2025 need both permissions for CloudFront.
resource "aws_lambda_permission" "api_url_from_cloudfront" {
  statement_id           = "cloudfront-invoke-function-url"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.site.arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "api_from_cloudfront" {
  statement_id             = "cloudfront-invoke-function"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.api.function_name
  principal                = "cloudfront.amazonaws.com"
  source_arn               = aws_cloudfront_distribution.site.arn
  invoked_via_function_url = true
}

resource "aws_cloudfront_origin_access_control" "api" {
  name                              = local.api_name
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# The API sets Cache-Control; these bounds only cap it. No origin request policy, so the
# viewer's Host header isn't forwarded: the function URL needs its own.
resource "aws_cloudfront_cache_policy" "api" {
  name        = local.api_name
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 86400

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    query_strings_config {
      query_string_behavior = "all"
    }

    headers_config {
      header_behavior = "none"
    }

    cookies_config {
      cookie_behavior = "none"
    }
  }
}
