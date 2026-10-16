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

We need four roles:

| Role | Used by | Can |
|---|---|---|
| `pegel_owner` (exists already) | migrations in CI | change the schema |
| `pegel_jobs` | ingest, clean, forecast, train, backup | read and write data |
| `pegel_api` | the FastAPI app | read only |
| `pegel_grafana` | Grafana Cloud ([setup-grafana.md](setup-grafana.md)) | read only |

Neon names the owner role after the database, so with `pegel` it is `pegel_owner`.

Create `pegel_jobs` and `pegel_api` in the **SQL editor** on the `prod` branch, not under "Roles" in the console. Roles created in the console become members of `neon_superuser`, which is far more than they need.

Generate two strong passwords in your password manager, then run:

```sql
CREATE ROLE pegel_jobs LOGIN PASSWORD '<password from password manager>';
CREATE ROLE pegel_api LOGIN PASSWORD '<password from password manager>';
```

`pegel_grafana` came later, after the `dev` branch existed, so create it on `dev` too, with its own password. The limits keep a dashboard from tying up the small compute:

```sql
CREATE ROLE pegel_grafana LOGIN PASSWORD '<password from password manager>' CONNECTION LIMIT 3;
ALTER ROLE pegel_grafana SET statement_timeout = '15s';
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

The jobs Lambda reads the pooled `prod` string for `pegel_jobs` from the secret `deilbach-pegel/jobs-database-url`. How to set it is in [setup-aws.md](setup-aws.md). The API reads the pooled `prod` string for `pegel_api` from `deilbach-pegel/api-database-url`, set the same way.

The console doesn't know the passwords of `pegel_jobs` and `pegel_api`, because you set them in SQL. Its connection strings for these roles carry the wrong password; use the one from your password manager.

## 7. Local development

Put the **`dev`** connection strings in `.env.local`, never the `prod` ones: `DATABASE_URL` (direct, owner role), `JOBS_DATABASE_URL` and `API_DATABASE_URL` (pooled). `.env.example` lists them.

## Good to know

- **Backups.** The free plan keeps 6 hours of restore history and has no scheduled backups. The nightly `backup` job (`pg_dump` to S3) is our real backup.
- **Public endpoint.** IP allow lists aren't available on the free plan, so the database is reachable from the internet. Access needs a password over TLS. Use long random passwords and give each role only what it needs.
- **If the CU-hours run out,** the database is suspended until next month. The main page keeps working from the S3 JSON; only the history selector stops. Check usage now and then under Billing in the console.
