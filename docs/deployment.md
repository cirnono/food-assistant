# Deployment

## Environment-variable deployment

```bash
cp .env.example .env
mkdir -p data
docker compose up -d --build
docker compose ps
```

Set server-side token variables in `.env`, restrict its permissions, and ensure
it is excluded from backups that are shared publicly.

## Docker Secrets deployment

Create `secrets/food_assistant_api_token` and `secrets/mealie_token`. Each file
contains only its credential.

```bash
chmod 600 secrets/*
docker compose -f compose.yaml -f compose.auth.yaml up -d --build
```

To keep credentials outside the repository directory, set these variables in
the ignored `.env` file to absolute host paths:

```dotenv
FOOD_ASSISTANT_API_TOKEN_HOST_FILE=/path/to/food_assistant_api_token
MEALIE_TOKEN_HOST_FILE=/path/to/mealie_token
```

Do not set `COMPOSE_FILE`; invoke the explicit `-f` command above so the
selected overlays remain visible and reproducible.

For an OpenAI-compatible LLM key, also create `secrets/llm_api_key` and run:

```bash
docker compose -f compose.yaml -f compose.auth.yaml \
  -f compose.llm-secret.yaml up -d --build
```

The LLM secret defaults to the ignored `secrets/llm_api_key`. Set
`LLM_API_KEY_HOST_FILE=/path/to/llm_api_key` to use an external host file.

The data bind mount defaults to `./data`. Existing installations using another
host path should set `FOOD_ASSISTANT_DATA_DIR` before recreating the container.
Do not copy source repositories, recipe downloads, or databases into the Git
repository.

For external access, put the service behind an HTTPS reverse proxy, prevent
direct origin access, and add access control for `/review`. Check `/healthz` for
liveness and `/readyz` for database readiness. Back up data and secrets
separately and test restoration before upgrades.
