# Architecture

How the forecast gets from the gauges to the website. Why we picked these parts is in [decisions/0001-architecture.md](decisions/0001-architecture.md).

## Overview

```
EventBridge Scheduler (hourly, weekly, nightly)
        │
        ▼
Lambda functions, all from one Docker image (Python)
  ingest    client DB (mTLS, read only), public gauges, DWD rain
  clean     raw → cleaned series
  forecast  48 h forecast, ranges, category chances
  train     weekly; promotes a new model only if it beats the current one
  backup    nightly pg_dump of Neon to S3
  api       read-only HTTP endpoints for the website
        │                         │
        ▼                         ▼
Neon Postgres (Frankfurt)    S3 "data": raw files, models, backups,
observations, forecasts,     precomputed JSON for the website
model metadata

CloudFront (one domain)
  /        → S3 "site": static Astro build
  /api/*   → API Gateway → api Lambda → Neon
  /data/*  → S3 "data": latest forecast and recent history as JSON
```

Everything on AWS runs in `eu-central-1` (Frankfurt).

## Jobs

One Python codebase, built into one Docker image. Each Lambda runs the same image with a different entry point. The Lambda handlers stay thin: they read the time window and call a plain Python function. So the same image also runs locally, on a VPS cron or on another cloud.

| Job | Schedule | Does |
|---|---|---|
| ingest | hourly | Fetches new readings and rain data, stores them raw |
| clean | hourly, after ingest | Removes spikes, fills short gaps, keeps levels down to −0.25 m |
| forecast | hourly, after clean | Writes the forecast to Neon and the website JSON to S3 |
| train | weekly | Retrains, compares with the current model and the baseline, promotes if better |
| backup | nightly | `pg_dump` of Neon to S3 |

Every job takes its time window as a parameter and upserts on natural keys, so reruns and backfills are safe.

The Lambdas run outside a VPC. That gives them internet access without a NAT gateway (~€35/month). If the client's database needs a fixed source IP, we add a small NAT instance (~€7/month).

If training ever takes longer than Lambda's 15 minutes, the same image runs as an ECS Fargate task instead.

## Storage

**Neon Postgres (Free plan, Frankfurt)** holds observations (raw and cleaned), forecasts and model metadata. That's about 100 MB per year; the free plan allows 1 GB.

Neon suspends the database when it's idle and wakes it on the next connection. The free plan includes 100 compute hours per month. If they run out, the database stays off until the next month. That's why the website mostly reads JSON from S3 instead of hitting the database (see below).

Two database roles: the jobs write, and the API can only read. Neon is set up by hand once, following [setup-neon.md](setup-neon.md); the schema and grants come from migrations.

**S3** holds what doesn't belong in a database:
- raw rain grids and other raw files
- trained models with their metadata
- nightly database backups
- the precomputed JSON for the website

## API and website

The website is static: Astro with React (TypeScript), built to plain HTML/JS/CSS and served from S3 through CloudFront. Texts like the category table are plain HTML. The interactive part (current level, forecast chart, history selector) is one React component that loads data in the browser.

Data comes from two places:

- **`/data/*.json` on S3.** The hourly forecast job writes the latest forecast and the last few days of observations here. The main page only needs these, so normal visits never touch the database.
- **`/api/history?from=…&to=…`.** API Gateway and a small Lambda query Neon for any past range. The history selector uses this.

Caching keeps Neon within its free hours:
- The selector rounds ranges to whole days, so repeat requests hit the cache.
- Responses for ranges that are fully in the past are cached for days. Ranges that include today are cached for an hour at most.

Every forecast shows when it was made and the time of the newest reading it used. If data is late, the page says so.

## Infrastructure

- **OpenTofu** describes everything on AWS. No manual changes in the console.
- **ECR** stores the Docker image.
- **Secrets Manager** holds the mTLS certificate and key, the client DB credentials and the Neon connection strings.
- **GitHub Actions** builds, tests and deploys.

No alerting for now. The website shows stale data clearly; a CloudWatch alarm with email can be added later at no cost.

## Costs

| Part | per month |
|---|---|
| Lambda, API Gateway, EventBridge, CloudFront | €0 (free tier) |
| S3, ECR | < €1 |
| Secrets Manager (3 secrets) | ~€1.20 |
| Route 53 hosted zone | €0.50 |
| Neon | €0 (Free plan) |
| **Total** | **~€2–4** |

Plus ~€7 if the client needs a fixed IP. Plus the domain itself.

If Neon's free plan stops being enough, its paid plan is pay-as-you-go with no minimum. For us that's a few euros a month.

## Open questions

- Does the client's database need a fixed source IP besides the mTLS certificate?
- Which domain do we use?
- Who runs the Langenberg gauge, is there an API, and may we show its data?
- Where do we get historical rain forecasts for training? DWD keeps them only briefly; Open-Meteo has an archive.
