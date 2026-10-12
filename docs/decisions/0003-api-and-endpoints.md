# 0003 · API delivery and endpoints

- **Status:** accepted
- **Date:** 2026-10-12

## Context

[0001](0001-architecture.md) put the API on API Gateway and let the website read JSON files straight from S3. We wanted one documented way to get the data, used by the website and by anyone else, without waking Neon on every page view.

## Decisions

### CloudFront calls the Lambda function URL directly

CloudFront signs its requests to the function URL, so the URL accepts nothing else. API Gateway would only add a service to configure; we don't need its API keys, usage plans or request validation. FastAPI validates input, and the docs come from FastAPI too. If a paid tier ever needs API keys, API Gateway can go in front later without changing the app.

### The website uses the API too

The page gets all its data from `/api/forecast` and `/api/history`. The S3 data bucket becomes private, and CloudFront has two origins: the website files and the API.

The forecast and the last 7 days of observations are files on S3, written every hour. The API serves those requests from the files, so only older history reaches Neon. Polling `/api/forecast` can't use up Neon's free hours.

The page now depends on the Lambda. Responses allow `stale-if-error` for a day, so CloudFront serves the last good response if the Lambda fails. The response always carries its timestamps, so the page still shows that the data is old.

### API docs are public

`/api/docs` and `/api/openapi.json` are public. The API is read only and shows nothing the page doesn't. The generated `openapi.json` is committed, so API changes show up in pull requests.

## Rejected

- **API Gateway.** Works, but one more service for features we don't use.
- **Website reads S3 files directly.** Keeps the page up if the Lambda breaks, but gives two ways to get the same data.
- **`/api/forecast` from Neon.** Simpler code, but every uncached request wakes the database.
- **Docs only locally.** Hides nothing worth hiding, and loses a handy reference.

## Consequences

- Cold starts: the first request after a quiet period waits 1–2 seconds. The 5-minute cache hides most of them.
- The API Lambda's reserved concurrency of 5 caps costs and load on Neon.
