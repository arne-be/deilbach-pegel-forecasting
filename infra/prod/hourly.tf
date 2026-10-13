# The hourly run: a Lambda from the jobs image, started by EventBridge Scheduler at :30.

locals {
  hourly_name = "deilbach-pegel-run-hourly"
  secrets = [
    aws_secretsmanager_secret.influx,
    aws_secretsmanager_secret.influx_client_cert,
    aws_secretsmanager_secret.influx_client_key,
    aws_secretsmanager_secret.jobs_database_url,
  ]
}

resource "aws_cloudwatch_log_group" "hourly" {
  name              = "/aws/lambda/${local.hourly_name}"
  retention_in_days = 30
}

resource "aws_iam_role" "hourly" {
  name = local.hourly_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "hourly" {
  role = aws_iam_role.hourly.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.hourly.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = [for secret in local.secrets : secret.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.data.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.data.arn
      },
    ]
  })
}

resource "aws_lambda_function" "hourly" {
  function_name = local.hourly_name
  role          = aws_iam_role.hourly.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.jobs.repository_url}:${var.jobs_image_tag}"
  architectures = ["arm64"]
  # Lambda's maximum. Normal runs take seconds; if every source stalls, their own timeouts and
  # retries add up to about 11 minutes (the rain forecast step at most about 4, as it starts no
  # older run after 2 minutes), and the level forecast is saved last.
  timeout     = 900
  memory_size = 512
  # shortcut: no reserved concurrency of 1, because AWS refuses any reservation while the
  # account limit is 10. Overlapping runs are safe since every write is an upsert. Add it
  # back once the Lambda concurrency quota is raised.

  environment {
    variables = {
      INFLUX_DATABASE                = "level"
      INFLUX_TIMEOUT                 = "30"
      INFLUX_SECRET_NAME             = aws_secretsmanager_secret.influx.name
      INFLUX_CLIENT_CERT_SECRET_NAME = aws_secretsmanager_secret.influx_client_cert.name
      INFLUX_CLIENT_KEY_SECRET_NAME  = aws_secretsmanager_secret.influx_client_key.name
      JOBS_DATABASE_URL_SECRET_NAME  = aws_secretsmanager_secret.jobs_database_url.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.hourly, aws_iam_role_policy.hourly]
}

resource "aws_iam_role" "hourly_schedule" {
  name = "${local.hourly_name}-schedule"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "hourly_schedule" {
  role = aws_iam_role.hourly_schedule.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.hourly.arn
    }]
  })
}

resource "aws_scheduler_schedule" "hourly" {
  name                         = local.hourly_name
  schedule_expression          = "cron(30 * * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.hourly.arn
    role_arn = aws_iam_role.hourly_schedule.arn

    # The next run is an hour later anyway; don't let a late start pile up.
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 900
    }
  }
}
