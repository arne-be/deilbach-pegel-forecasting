# 0001 · Architecture and hosting

- **Status:** accepted
- **Date:** 2026-10-12

## Context

We need hourly jobs, a small database, a read-only API and one public web page. The data is tiny: about ten hourly series, under 1 GB for years. The budget is under €10 a month, and mostly one person runs it.

Two wishes shaped the choices: stay cheap, and don't get locked into one cloud.

The result is described in [architecture.md](../architecture.md).

## Decisions

### Jobs: one Docker image on Lambda

Lambda costs nothing at our volume and needs no server. We package the code as a Docker image with thin handlers, so the same code runs anywhere. That keeps us portable for about half a day of extra work.

Rejected:
- **Plain zip Lambdas.** Simpler at first, but tied to Lambda.
- **An always-on VM.** Cheap, but we'd have to patch and watch it.

### Database: Neon Postgres, free plan

We want real SQL: upserts for idempotent jobs, migrations, and the option to look at the data with any tool. Neon gives us Postgres in Frankfurt for €0, and its paid plan costs a few euros if we outgrow the free one.

The catch is the 100 compute hours per month. When they run out, the database is off until the next month. We avoid that by serving the main page from JSON files on S3 and caching history queries.

Rejected:
- **Parquet files on S3 + DuckDB.** Almost free and portable, but no real upserts or migrations, and no database to query ad hoc.
- **Supabase (free).** Always on, so no compute limit. But only 500 MB of storage, half of Neon's, and it pauses after a week without activity.
- **RDS or Aurora Serverless.** Real Postgres inside AWS, but ~€15–20 a month for RDS. Aurora takes ~15 seconds to wake up, too slow for a public page.
- **ClickHouse Cloud.** No free plan, ~$67 a month at minimum, and built for billions of rows, not ours.
- **TimescaleDB (Tiger Cloud).** No lasting free plan, from $30 a month. At under a million rows, plain Postgres is just as fast.
- **DynamoDB.** Practically free, but awkward for time-range queries and strongly tied to AWS.

Neon runs outside our AWS account. We accept that for real Postgres at no cost.

### Hosting: S3 + CloudFront

The site is static files. CloudFront sits in front of both the site and the API, which gives us one domain (no CORS) and one cache. The cache matters: it keeps Neon within its free hours and absorbs the traffic during a flood.

Rejected:
- **Vercel.** The free plan forbids commercial use, so we'd pay $20 a month.
- **Cloudflare Pages, Netlify.** Free and comfortable, with preview links per pull request. But it's one more vendor, and routing `/api/*` to AWS takes extra setup.
- **AWS Amplify Hosting.** Easy deploys, but harder to put the API under the same domain and mostly outside OpenTofu.

### Frontend: Astro with React and TypeScript

The site is mostly text plus one interactive part: current level, forecast chart and history selector. Astro builds real HTML pages and loads JavaScript only for that one part. React builds on what we already know and is widely used. The React component isn't tied to Astro, so it can move if the site grows into an app.

Rejected:
- **Next.js.** Built for running on a server. As static files on S3 it loses most of its features.
- **React or Vue as a single-page app.** The page stays blank until the JavaScript loads, and S3 needs routing workarounds.
- **SvelteKit.** A good fit and easy to learn, but we'd start from zero instead of building on React.
- **Python dashboards (Streamlit, Dash).** Need a server that runs all the time, and they don't handle traffic spikes well.

### Infrastructure as code: OpenTofu

OpenTofu is open source, works with any cloud, and the skill carries over. For our ~15 resources it takes about as long as AWS CDK.

Rejected:
- **AWS CDK.** Python throughout would be nice, but it only works with AWS.
- **SAM / Serverless Framework.** Focused on Lambda and less flexible for everything else.

### No alerts for now

The page shows clearly when data is late, and one person runs the system. This goes against our rule to monitor freshness. A CloudWatch alarm with email costs nothing and can be added any time.

## Consequences

- Running costs stay at ~€2–4 a month.
- We have three vendors: AWS, Neon and GitHub.
- The website must read from the S3 JSON files by default and only call the API for history. Otherwise Neon's free hours run out.
- If the paid login comes, Astro can render some pages on a server, or the React part moves to a full app framework.
