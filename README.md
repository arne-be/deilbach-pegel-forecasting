# deilbach-pegel-prediction

Hourly water level forecast for the **Deilbach at Kupferdreh** (Essen), 48 hours ahead, with flood categories and an uncertainty range, published on a public website.

> The forecast is an estimate, not an official flood warning (*keine amtliche Hochwasserwarnung*).

## What it does

**Data (hourly)**
- Latest water level from the client's Deilbach gauge in Kupferdreh.
- Water levels from public gauges further upstream (e.g. Langenberg).
- Observed rain and rain forecasts for the Deilbach catchment around Velbert.
- Everything is stored in our own database on AWS. Source systems are **read only**.
- Spikes and gaps are cleaned automatically. Raw readings are kept, shifted to our zero point; cleaned levels never drop below 0.

**Forecast**
- A new forecast every hour for the next 48 hours.
- Shown as the highest expected level in the next **3, 24 and 48 hours**, each with its flood category.
- Each forecast has a likely range, derived from the errors of past forecasts. The same range gives the chance of reaching each category.
- A simple baseline forecast is built first, so we can check whether the real model adds value.
- The model is retrained weekly. A new model only replaces the current one if it performs better.

**Website**
- One public page in German, no login: current level, 48-hour forecast chart, flood categories, short explanations.
- If data is late or missing, the page says so clearly instead of showing an old forecast as current.
- A paid login (annual fee) may be added later.

## Flood categories

Levels are relative to the local zero point, 45 cm below the concrete ledge of the sewer outlet. The water never drops below it, so levels are never negative. All levels are in centimetres.

| Category | Level | What happens |
|---|---|---|
| 1 · unkritisch | up to 145 cm | No action needed. |
| 2 · kritisch | 145–165 cm | From 165 cm: close the backflow valve and connect the pump. The Deilbach overflows at the Kupferdreh car park. |
| 3 · sehr kritisch | 165–185 cm | From 185 cm water goes over the wall. Set up mobile flood barriers. |
| 4 · extrem kritisch | 185–225 cm | Barriers and raised wall keep water out of the yard. Lay sandbags in the yard. |
| 5 · Chaos | above 225 cm | Water flows into the yard. Clear the ground floor flat, switch off power. |

## Plan (first version, one week)

| Day | Work |
|---|---|
| 1 | Connect to the client's database, store the data, build the baseline forecast. |
| 2 | Add the public gauges and rain data, clean the data. |
| 3 | Train and evaluate the model, add the uncertainty range. |
| 4 | Run it hourly on AWS, add weekly retraining, test. |
| 5 | Build the website. |

## Local setup

**Access to the source database** (InfluxDB 1.8, host on request) needs a client certificate *and* a read-only username/password.

1. Store the certificate and key outside the repo:
   ```
   mkdir -p ~/.config/deilbach-pegel && chmod 700 ~/.config/deilbach-pegel
   mv deilbach-pegel.crt deilbach-pegel.key ~/.config/deilbach-pegel/
   chmod 600 ~/.config/deilbach-pegel/deilbach-pegel.key
   ```
2. Create the config files from the template (both are gitignored):
   ```
   cp .env.example .env && touch .env.local && chmod 600 .env .env.local
   ```
   Put the cert/key paths in `.env`, and `INFLUX_URL`, `INFLUX_USERNAME` and `INFLUX_PASSWORD` in `.env.local`. The repo is public, so the host stays out of it too. Your password manager stays the source of truth; `.env.local` is a copy.
3. Check the connection with a read-only query (needs `jq`). With no argument it lists the measurements:
   ```
   scripts/influx-query.sh
   scripts/influx-query.sh "SELECT * FROM \"level\" WHERE \"label\" = 'Deilbach' ORDER BY time DESC LIMIT 5"
   ```
   The data is in measurement `level`, tags `label` and `device`, fields `level` (mm, relative to the concrete ledge, so often negative; ingest adds 45 cm to move it to our zero point) and `battery`. Readings are hourly, starting 2023-03-06.
4. Enable the secret scan before your first commit:
   ```
   brew install gitleaks
   git config core.hooksPath .githooks
   ```
   CI runs the same scan on every pull request.

On AWS, credentials and the client key come from AWS Secrets Manager, not from env files.

## Known limitations

- **Few floods in the data.** Records start in March 2023. The highest level so far was 165 cm on 19.11.2024; there are no examples of category 3 or higher. The model will be reliable in normal conditions and much less certain in the situations that matter most.
- **Short lead time from gauges.** Langenberg leads Kupferdreh by about one hour. Beyond a few hours the forecast depends almost entirely on the rain forecast, which is often off for a small catchment.
- **Data access.** Still to confirm: automatic access to the public gauge data, how far back it goes, and whether we may show it on the website.
- **Historical rain forecasts** may be hard to find, which limits how well the model can learn from them.

## Status

Planning. No code yet. The architecture is in [docs/architecture.md](docs/architecture.md), and the reasons behind it in [docs/decisions/](docs/decisions/).
