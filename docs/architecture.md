# Architecture

Food Assistant is a single FastAPI service with a browser review page and a
SQLite database. Routers cover inventory, recommendations, user-configured
recipe sources, AI normalization, import queues, Mealie integration, and system
status. SQLAlchemy models are created at startup; small historical migrations
are applied by application code rather than Alembic.

```mermaid
sequenceDiagram
  participant Source as User recipe source
  participant FA as Food Assistant
  participant LLM as LLM provider
  participant Human as Reviewer
  participant Mealie
  Source->>FA: Synchronize metadata/content
  FA->>LLM: Structured normalization request
  LLM-->>FA: JSON recipe
  FA->>FA: Repair, validate, quality gate, deduplicate
  FA-->>Human: Review candidate
  Human->>FA: Edit/approve
  FA->>Mealie: Create or update recipe
  FA->>Mealie: Read back and verify
  FA->>FA: Store idempotent import record
```

`app/llm/` owns provider configuration, construction, JSON extraction, and
sanitized errors. Business code asks the provider factory for structured chat.
The compatibility module `app/ollama_client.py` retains historical imports.

All `/api/v1/*` requests pass through constant-time API-token authentication.
Health, readiness, documentation, and the `/review` HTML document are outside
that middleware; the review page cannot read protected data without a token.
