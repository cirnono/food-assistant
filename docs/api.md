# API

Interactive OpenAPI documentation is served at `/docs`. Every `/api/v1/*`
endpoint requires one of:

```http
Authorization: Bearer <food-assistant-token>
```

or:

```http
X-Food-Assistant-Token: <food-assistant-token>
```

Public utility routes are `GET /healthz`, `GET /readyz`, and the `/review` HTML
page. Major protected groups are:

- `/api/v1/inventory`
- `/api/v1/recommendations`
- `/api/v1/sources`
- `/api/v1/ai/recipe/normalize`
- `/api/v1/import-jobs`
- `/api/v1/integrations/mealie/status`
- `/api/v1/integrations/ollama/status` (legacy compatibility)
- `/api/v1/system/llm-status`
- `/api/v1/system/llm-test`

`llm-status` returns only public configuration metadata and booleans. `llm-test`
performs a minimal structured request, writes no database data, and returns
provider, model, success, and latency. Errors are sanitized.

Consult `/docs` for current request and response schemas. Clients should treat
5xx responses as retryable only when appropriate and should use import job and
item identifiers to preserve idempotency.
