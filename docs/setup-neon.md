# Neon setup

Neon is set up by hand once; the reasons are in [architecture.md](architecture.md). Tables, indexes and grants don't belong here. They come from migrations in the repo.

Do the steps in this order. Roles are copied when a branch is created, so the roles must exist before the `dev` branch.

## 1. Project

In the Neon console, create a project:

- **Name:** `deilbach-pegel`
- **Region:** AWS Europe Central 1 (Frankfurt)
- **Postgres version:** the default Neon offers
- **Database name:** `pegel`

The default branch is production. Rename it to `prod` so it can't be mixed up with the `main` git branch.

## 2. Compute size

Under the `prod` branch → Compute → Edit, set the autoscaling range to **0.25–0.25 CU**.

The free plan gives 100 CU-hours a month. A fixed small size makes them last as long as possible, and our queries are tiny. The database still suspends after 5 minutes without queries; the free plan doesn't let you change that.

## 3. Roles

We need three roles:

| Role | Used by | Can |
|---|---|---|
| `pegel_owner` (exists already) | migrations in CI | change the schema |
| `pegel_jobs` | ingest, clean, forecast, train, backup | read and write data |
| `pegel_api` | the FastAPI app | read only |

Neon names the owner role after the database, so with `pegel` it is `pegel_owner`.

Create `pegel_jobs` and `pegel_api` in the **SQL editor** on the `prod` branch, not under "Roles" in the console. Roles created in the console become members of `neon_superuser`, which is far more than they need.

Generate two strong passwords in your password manager, then run:

```sql
CREATE ROLE pegel_jobs LOGIN PASSWORD '<password from password manager>';
CREATE ROLE pegel_api LOGIN PASSWORD '<password from password manager>';
```

The grants (`USAGE`, `SELECT`, `INSERT`, …) come from the migrations, not from here.

## 4. Dev branch

Create a branch `dev` from `prod`. It gets a copy of the data and of the roles.

The branch gets its own compute. Set it to **0.25–0.25 CU** as well, as in step 2: both branches share the 100 CU-hours a month.

Then give the roles on `dev` new passwords, so local credentials can never reach production. Run this in the SQL editor with the `dev` branch selected:

```sql
ALTER ROLE pegel_jobs PASSWORD '<new dev password>';
ALTER ROLE pegel_api PASSWORD '<new dev password>';
```

Reset `dev` from `prod` whenever you want fresh data: in the console, open the branch and choose Reset from parent. Then run this step again: the reset copies the branch from `prod` again, so the roles may have the prod passwords again.

## 5. Connection strings

Neon offers a direct and a pooled connection string for each role (the pooled host contains `-pooler`).

- **Jobs and API:** pooled. Many short Lambda runs open connections, and the pooler keeps that cheap.
- **Migrations:** direct. Some schema changes don't work through the pooler.

Always keep `sslmode=require` in the string.

## 6. Production secrets

OpenTofu creates three empty secrets in AWS Secrets Manager. Run `tofu apply` before this step. The values are set by hand, so they never end up in the OpenTofu state.

| Secret | Value |
|---|---|
| `deilbach-pegel/neon/migrations` | direct string, `pegel_owner`, branch `prod` |
| `deilbach-pegel/neon/jobs` | pooled string, `pegel_jobs`, branch `prod` |
| `deilbach-pegel/neon/api` | pooled string, `pegel_api`, branch `prod` |

To set a value without it showing up in your shell history or the process list:

```
read -rs NEON_URL          # paste the string, press Enter
tmp=$(mktemp) && chmod 600 "$tmp" && printf '%s' "$NEON_URL" > "$tmp"
aws secretsmanager put-secret-value --secret-id deilbach-pegel/neon/jobs --secret-string "file://$tmp"
rm "$tmp"; unset NEON_URL
```

Repeat for the other two secrets.

## 7. Local development

Put the **`dev`** connection strings in `.env.local`, never the `prod` ones. The variable names will be added to `.env.example` together with the first code that uses them.

## Good to know

- **Backups.** The free plan keeps 6 hours of restore history and has no scheduled backups. The nightly `backup` job (`pg_dump` to S3) is our real backup.
- **Public endpoint.** IP allow lists aren't available on the free plan, so the database is reachable from the internet. Access needs a password over TLS. Use long random passwords and give each role only what it needs.
- **If the CU-hours run out,** the database is suspended until next month. The main page keeps working from the S3 JSON; only the history selector stops. Check usage now and then under Billing in the console.
