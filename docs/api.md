# API

## Consumption and shopping (0.25.0)

- `GET /api/v1/consumption-reviews` and `/pending` list stable post-cooking proposals.
- `POST /api/v1/consumption-reviews/{id}/confirm`, `/dismiss`, and `/undo` require matching owner and confirmation IDs. Confirmation is transactional and undo writes reversal audit rows.
- `GET/POST /api/v1/shopping-list`, `PATCH /api/v1/shopping-list/{id}`, and the `/complete`, `/dismiss`, `/restore` actions manage the local list.
- `POST /api/v1/shopping-list/from-recipe` revalidates current recipe ingredients server-side; it does not trust arbitrary browser names.

No cooking-finish or proposal endpoint changes inventory. Shopping additions caused by consumption happen only when explicitly requested during confirmation.

## Cooking sessions

All `/api/v1/cooking-sessions/*` endpoints use the existing Food Assistant API
token. Start with `POST /api/v1/cooking-sessions/start`, read the owner session
with `GET /active`, and use the confirmed step, ingredient, finish, and cancel
actions under `/{session_id}`. A recipe snapshot is fixed for the life of the
session. Finishing writes cooking history and returns a read-only inventory
consumption preview; it never decrements inventory.

Timer endpoints live under `/{session_id}/timers`. Running timers persist one
UTC deadline rather than writing every second. Paused timers persist remaining
seconds. `GET /api/v1/cooking-sessions/active-state` is a lightweight local-only
polling endpoint suitable for Home Assistant.

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
- `/api/v1/cooking-sessions`
- `/api/v1/home-assistant`
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

Import item actions include:

- `POST /api/v1/import-jobs/{job_id}/items/{item_id}/process` to process one
  confirmed queued item without automatic import
- `POST /api/v1/import-jobs/{job_id}/items/{item_id}/restore-rejected` to
  return a confirmed rejected item to human review without calling the LLM

Duplicate source revisions are resolved through the dry-run-first
`app.maintenance.resolve_duplicate_import` CLI. It never decides from a recipe
name or Mealie slug alone and never modifies an existing Mealie recipe.

Consult `/docs` for current request and response schemas. Clients should treat
5xx responses as retryable only when appropriate and should use import job and
item identifiers to preserve idempotency.
# Pantry and recommendations

Authenticated pantry endpoints are available at `/api/v1/inventory`, including
`/summary` and the `/{id}/consume`, `/{id}/restock`, and `/{id}/open` actions.
An omitted quantity means the item is known to be available without an exact
count; zero means out of stock.

`GET /api/v1/recommendations` returns `ready_now`, `missing_one_or_two`,
`use_soon`, and `random_pick` groups. Every result includes ingredient matches,
missing ingredients, expiry matches, score reasons, timing, classification, and
a Mealie link. The old `/preview` endpoint remains available but is deprecated.

Ingredient aliases are managed under `/api/v1/ingredient-aliases`, and cooking
history under `/api/v1/cooking-history`. All `/api/v1/*` routes require the Food
Assistant API token.
