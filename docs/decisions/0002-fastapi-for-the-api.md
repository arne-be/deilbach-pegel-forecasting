# 0002 · FastAPI for the API

- **Status:** accepted
- **Date:** 2026-10-12

## Context

The website needs one real endpoint: `/api/history`, which queries Neon for any time range. [0001](0001-architecture.md) put it on API Gateway and Lambda but didn't say how to write it.

## Decision

We write the API with FastAPI and run it on Lambda through the AWS Lambda Web Adapter.

The adapter starts FastAPI as a normal web server inside the container. So the API image runs on Lambda, locally with `uvicorn`, or on any server. That fits our wish not to be locked into one cloud.

FastAPI also gives us input checks through Pydantic, a test client for local tests, and OpenAPI docs for free.

Rejected:
- **Plain Lambda handler.** Least code for one endpoint, but it only runs on Lambda, and we'd write input checks and local testing ourselves.
- **FastAPI with Mangum.** Also works, but Mangum translates Lambda events in code, so the app still depends on Lambda. With the Web Adapter the app doesn't know about Lambda at all.
- **Flask or Django.** Flask has no built-in input checks; Django is far too big for one endpoint.

## Consequences

- One more dependency to keep updated.
- Cold starts get a few hundred milliseconds slower. CloudFront caching hides most of that.
- The Dockerfile gets a second build target for the API, which adds the Web Adapter. The jobs image stays without it, because the adapter expects a web server and would get in the way of plain job handlers.
