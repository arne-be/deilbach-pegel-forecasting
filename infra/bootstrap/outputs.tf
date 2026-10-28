output "tf_state_bucket" {
  description = "State bucket for infra/prod. GitHub variable TF_STATE_BUCKET."
  value       = aws_s3_bucket.tofu_state.id
}

output "aws_plan_role_arn" {
  description = "Role for tofu plan on pull requests. GitHub variable AWS_PLAN_ROLE_ARN."
  value       = aws_iam_role.github_plan.arn
}

output "aws_deploy_role_arn" {
  description = "Role for deploys from main. GitHub variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.github_deploy.arn
}

output "aws_triage_role_arn" {
  description = "Role for the alert triage workflow. GitHub variable AWS_TRIAGE_ROLE_ARN."
  value       = aws_iam_role.github_triage.arn
}
