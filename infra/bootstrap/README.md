# infra/bootstrap

Creates what `infra/prod` and CI need before they can run:

- the S3 bucket for the `infra/prod` state (`deilbach-pegel-tofu-state-<account id>`, key `prod/terraform.tfstate`, OpenTofu's S3 locking),
- the GitHub OIDC provider,
- the role `deilbach-pegel-github-plan` for `tofu plan` in pull requests (read only, no secret values),
- the role `deilbach-pegel-github-deploy` for deploys from `main` (only resources named `deilbach-pegel*`).

You apply it by hand once, with admin credentials. CI never touches it. The state of this folder stays local, because it creates the bucket a remote backend would need.

## Apply

From the repo root, with the tools from `mise install`:

```
aws login
cd infra/bootstrap
tofu init
tofu plan
tofu apply
```

Then set the GitHub repository variables from the outputs:

```
gh variable set TF_STATE_BUCKET --body "$(tofu output -raw tf_state_bucket)"
gh variable set AWS_PLAN_ROLE_ARN --body "$(tofu output -raw aws_plan_role_arn)"
gh variable set AWS_DEPLOY_ROLE_ARN --body "$(tofu output -raw aws_deploy_role_arn)"
```

Keep a copy of the local state, so later changes here don't start from scratch. The state holds no secrets:

```
aws s3 cp terraform.tfstate "s3://$(tofu output -raw tf_state_bucket)/bootstrap/terraform.tfstate"
```

## Changing it

When a deploy fails on a missing permission, widen the deploy role in `roles.tf`, open a PR, and after the merge run `tofu apply` here again by hand. The deploy role cannot change the CI roles itself.

The state bucket has `prevent_destroy`, so `tofu destroy` stops before deleting it.
