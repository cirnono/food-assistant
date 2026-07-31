# Configuration

Copy `.env.example` to `.env`. Never commit `.env` or secret files.

| Variable | Purpose | Default |
|---|---|---|
| `APP_VERSION` | Reported application version | `0.21.0` |
| `FOOD_ASSISTANT_DATA_DIR` | Host persistence directory for Compose | `./data` |
| `DATABASE_URL` | SQLAlchemy database URL | SQLite under `/data` |
| `FOOD_ASSISTANT_API_TOKEN[_FILE]` | API authentication | required |
| `MEALIE_BASE_URL` | Mealie origin | host gateway example |
| `MEALIE_TOKEN[_FILE]` | Mealie credential | required for imports |
| `LLM_PROVIDER` | `ollama` or `openai_compatible` | `ollama` |
| `LLM_BASE_URL` | Provider base URL | host Ollama example |
| `LLM_API_KEY[_FILE]` | Provider credential | empty |
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

Legacy Ollama variables are used only when the corresponding new value is
unset or empty: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`,
`OLLAMA_NUM_CTX`, and `OLLAMA_KEEP_ALIVE`. A non-sensitive deprecation warning
is emitted once.
