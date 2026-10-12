---
description: API design standards for route handlers and endpoints
paths:
  - "src/api/**"
  - "src/routes/**"
  - "src/routers/**"
  - "app/api/**"
---

# API Design

- Every endpoint must validate inputs at the boundary. Never trust raw request data.
- Return consistent error responses: `{ "error": { "code": "...", "message": "..." } }`.
- Use appropriate HTTP status codes: 201 for creation, 404 for not found, 422 for validation errors.
- Keep route handlers thin. Extract business logic into service functions.
- All endpoints must have request/response type definitions.
- Timestamps in responses are ISO 8601 in UTC; levels in metres as numbers. Formatting for display happens in the frontend.
- Forecast responses always include the issue time and the time of the newest observation used, so clients can detect stale data.
- Log errors with context (request ID, endpoint) — never log sensitive data (tokens, passwords).
- Add rate limiting and caching to any public-facing endpoint.
