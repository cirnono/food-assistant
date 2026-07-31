# Troubleshooting

## Authentication returns 401 or 503

Confirm the Food Assistant token is at least 32 characters and that the selected
environment variable or secret file is available inside the container. Recreate
the container after rotating a secret. Do not print the credential while
debugging.

## Ollama is unavailable

From the Docker host, verify the configured origin and model. Linux deployments
use the `host.docker.internal` host-gateway mapping in Compose. CUDA OOM,
connection refusal, timeout, and protocol disconnects are treated as
infrastructure failures; combined batches stop and affected items are requeued.

## OpenAI-compatible structured output fails

Use the authenticated LLM test endpoint. Confirm the base URL and model name,
then check whether the upstream supports `json_schema` or `json_object`. Food
Assistant falls back automatically, but the model must still produce a JSON
object. Upstream error bodies are deliberately truncated and sanitized.

## Mealie imports fail

Verify the Mealie origin, token permissions, and network reachability. Repeated
requests use import records to avoid duplicate writes. Do not manually delete
those records without understanding the associated Mealie recipe state.

## Database is locked

Ensure only the intended service instance writes the SQLite database and that
the data directory supports file locking. Stop the service before copying raw
database/WAL files, or use a SQLite-aware backup method.

## Compose validation

Run `docker compose config --quiet`, then `docker compose build`. If migrating
from a deployment-specific data path, set `FOOD_ASSISTANT_DATA_DIR` before
running `up`; otherwise Compose's safe default is `./data`.
