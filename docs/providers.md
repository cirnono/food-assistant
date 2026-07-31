# LLM Providers

## Ollama

Ollama uses `POST /api/chat`, non-streaming JSON mode, temperature, context,
prediction limit, keep-alive, and `think=false`. The model can be unloaded with
an empty `/api/generate` request after configured batch operations.

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=qwen3:8b
```

## OpenAI-compatible

The provider sends `POST /v1/chat/completions` when the configured base URL has
no path. When a path such as `/v1` is present, it is preserved. Authentication
uses `Authorization: Bearer` only when a key is configured.

The structured-output sequence is:

1. `response_format` with strict `json_schema`;
2. `json_object` after a format-related client error;
3. ordinary messages, extracting the first complete JSON object from content.

This accommodates many DeepSeek, OpenRouter, LM Studio, vLLM, and LiteLLM
deployments, but these products differ in schema support and error behavior.
Confirm compatibility with `POST /api/v1/system/llm-test`.

Provider errors are sanitized and normalized as `LLMProviderError`. Timeouts,
connection failures, upstream 5xx responses, `RemoteProtocolError`, and CUDA
out-of-memory failures remain identifiable as infrastructure errors so batch
processing can stop and requeue instead of damaging individual item state.
