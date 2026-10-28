# infra/bootstrap

Creates what `infra/prod` and CI need before they can run:

- the S3 bucket for the `infra/prod` state (`deilbach-pegel-tofu-state-<account id>`, key `prod/terraform.tfstate`, OpenTofu's S3 locking),
- the GitHub OIDC provider,
- the role `deilbach-pegel-github-plan` for `tofu plan` in pull requests (read only, no secret values except the Grafana and GitHub dispatch tokens),
- the role `deilbach-pegel-github-deploy` for deploys from `main` (only resources named `deilbach-pegel*`; it also reads the secret `deilbach-pegel/migrate-database-url` to migrate the prod database),
- the permissions boundary `deilbach-pegel-workload-boundary` (`boundary.tf`): the deploy role may only create or change `deilbach-pegel*` roles that carry it, so it can't create an admin role for itself,
- the role `deilbach-pegel-github-triage` for the alert triage workflow (`triage.tf`), only from the GitHub environment `alert-triage`: it calls Claude Sonnet on Bedrock (EU inference profile), reads the hourly Lambda log and the secret `deilbach-pegel/api-database-url`, and publishes to the SNS topic `deilbach-pegel-alert-triage`. Nothing else, not even read-only access,
- the empty secret `deilbach-pegel/grafana-token`, which the plan and deploy roles can read ([docs/setup-grafana.md](../docs/setup-grafana.md)),
- the empty secret `deilbach-pegel/github-dispatch-token`, a GitHub token with which Grafana starts the alert triage workflow; the plan and deploy roles can read it. `infra/prod` can't plan until it has a value ([docs/setup-grafana.md](../docs/setup-grafana.md)).

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
gh variable set AWS_TRIAGE_ROLE_ARN --body "$(tofu output -raw aws_triage_role_arn)"
```

Keep a copy of the local state, so later changes here don't start from scratch. The state holds no secrets:

```
aws s3 cp terraform.tfstate "s3://$(tofu output -raw tf_state_bucket)/bootstrap/terraform.tfstate"
```

## Changing it

When a deploy fails on a missing permission, widen the deploy role in `roles.tf`, open a PR, and after the merge run `tofu apply` here again by hand. The deploy role cannot change the CI roles itself.

Every role in `infra/prod` needs `permissions_boundary = local.workload_boundary_arn`; without it the deploy fails with AccessDenied. When a workload needs more than the boundary allows, widen it in `boundary.tf` and apply here before merging the `infra/prod` change. The same goes for anything `infra/prod` needs to exist first: apply here from the branch, then merge.

The state is local and gitignored, so it lives only in the main checkout (and the S3 copy). To apply from a worktree, copy `infra/bootstrap/terraform.tfstate` from the main checkout first and back afterwards. Without it, tofu starts from an empty state and tries to create everything again.

The state bucket has `prevent_destroy`, so `tofu destroy` stops before deleting it.
