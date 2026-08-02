# Configuration

Copy `.env.example` to `.env`. Never commit `.env` or secret files.

| Variable | Purpose | Default |
|---|---|---|
| `APP_VERSION` | Reported application version | `0.22.0` |
| `FOOD_ASSISTANT_DATA_DIR` | Host persistence directory for Compose | `./data` |
| `DATABASE_URL` | SQLAlchemy database URL | SQLite under `/data` |
| `FOOD_ASSISTANT_API_TOKEN[_FILE]` | API authentication | required |
| `FOOD_ASSISTANT_API_TOKEN_HOST_FILE` | Host file mounted by `compose.auth.yaml` | `./secrets/food_assistant_api_token` |
| `MEALIE_BASE_URL` | Mealie origin | host gateway example |
| `MEALIE_TIMEOUT_SECONDS` | Mealie response read timeout | `90` |
| `MEALIE_CONNECT_TIMEOUT_SECONDS` | Mealie connection timeout | `5` |
| `MEALIE_WRITE_TIMEOUT_SECONDS` | Mealie request write timeout | `10` |
| `MEALIE_POOL_TIMEOUT_SECONDS` | Mealie connection-pool wait timeout | `10` |
| `MEALIE_RECOMMENDATION_CONCURRENCY` | Concurrent recipe detail reads (clamped to 1–20) | `8` |
| `MEALIE_RECIPE_CACHE_TTL_SECONDS` | Successful recipe detail cache TTL (300–86400 seconds) | `21600` |
| `MEALIE_TOKEN[_FILE]` | Mealie credential | required for imports |
| `MEALIE_TOKEN_HOST_FILE` | Host file mounted by `compose.auth.yaml` | `./secrets/mealie_token` |
| `LLM_PROVIDER` | `ollama` or `openai_compatible` | `ollama` |
| `LLM_BASE_URL` | Provider base URL | host Ollama example |
| `LLM_API_KEY[_FILE]` | Provider credential | empty |
| `LLM_API_KEY_HOST_FILE` | Host file mounted by `compose.llm-secret.yaml` | `./secrets/llm_api_key` |
| `LLM_MODEL` | Provider model identifier | `qwen3:8b` |
| `LLM_TIMEOUT_SECONDS` | Total generation timeout | `300` |
| `LLM_CONNECT_TIMEOUT_SECONDS` | Connection timeout | `10` |
| `LLM_CONTEXT_LENGTH` | Ollama context target | `6144` |
| `LLM_MAX_TOKENS` | Maximum generated tokens | `4096` |
| `LLM_TEMPERATURE` | Sampling temperature | `0` |
| `LLM_KEEP_ALIVE` | Ollama keep-alive | `10m` |
| `LLM_UNLOAD_AFTER_BATCH` | Unload Ollama after a batch/test | `true` |

For the LLM credential, a non-empty `LLM_API_KEY_FILE` takes precedence over
`LLM_API_KEY`, and surrounding whitespace is removed. The Docker Secrets
overlays explicitly clear the corresponding environment credential. Secret file
contents are never returned by status APIs.

The `*_HOST_FILE` variables are evaluated by Docker Compose on the host; the
`*_FILE` variables identify the corresponding `/run/secrets/...` path inside
the container. Host files may live in the ignored repository `secrets/`
directory or at a custom absolute path. Prefer explicit Compose commands:

```bash
docker compose -f compose.yaml -f compose.auth.yaml up -d --build
```

Legacy Ollama variables are used only when the corresponding new value is
unset or empty: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`,
`OLLAMA_NUM_CTX`, and `OLLAMA_KEEP_ALIVE`. A non-sensitive deprecation warning
is emitted once.
