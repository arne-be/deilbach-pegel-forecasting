# AWS setup

GitHub Actions creates everything in `infra/prod/` on merge to `main`. Two things it can't do: put the secret values into Secrets Manager, and check that the first run works. Do these by hand once, after the first deploy.

The first deploy creates the secrets empty and starts the hourly schedule right away. So the first runs fail with a missing secret value until you fill them in. That's expected.

You need the AWS CLI logged in to the prod account, region `eu-central-1`.

## 1. Secret values

Each value is read from a file, so it never shows up in your shell history.

Client certificate and key, from where they already live:

```
aws secretsmanager put-secret-value --secret-id deilbach-pegel/influx-client-cert \
  --secret-string file://$HOME/.config/deilbach-pegel/deilbach-pegel.crt
aws secretsmanager put-secret-value --secret-id deilbach-pegel/influx-client-key \
  --secret-string file://$HOME/.config/deilbach-pegel/deilbach-pegel.key
```

Influx URL and credentials, as one JSON object. Write it in a temporary file only you can read, then delete it:

```
umask 077
tmp=$(mktemp)
$EDITOR "$tmp"
```

The file should contain the same values as your `.env.local`:

```
{"INFLUX_URL": "https://...", "INFLUX_USERNAME": "...", "INFLUX_PASSWORD": "..."}
```

```
aws secretsmanager put-secret-value --secret-id deilbach-pegel/influx --secret-string "file://$tmp"
rm "$tmp"
```

Jobs database: the pooled connection string of the Neon `prod` branch for the role `pegel_jobs` ([setup-neon.md](setup-neon.md)). The password is the one you set with `CREATE ROLE`, not the one the console shows; URL-encode special characters. Same pattern:

```
tmp=$(mktemp)
$EDITOR "$tmp"
aws secretsmanager put-secret-value --secret-id deilbach-pegel/jobs-database-url --secret-string "file://$tmp"
rm "$tmp"
```

## 2. Migrate prod

The `prod` branch starts empty. Migrate it with the direct (not pooled) `pegel_owner` string from the console, set for this one command only:

```
DATABASE_URL='<direct prod pegel_owner string>' mise exec -- dbmate --no-dump-schema migrate
```

Do the same after every merged migration.

## 3. Test run

Start a run and print its result:

```
aws lambda invoke --function-name deilbach-pegel-run-hourly /dev/stdout
```

A good run returns `issued_at` and `newest_observation_at`. If it fails, the logs say why:

```
aws logs tail /aws/lambda/deilbach-pegel-run-hourly --follow
```

After that, the schedule runs the job every hour at :30 UTC.

## Changing a secret later

Put the new value the same way. The next run reads it; nothing needs to be deployed.
