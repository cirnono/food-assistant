# Privacy

Food Assistant processes recipe source text, normalized recipes, review edits,
inventory data, and integration metadata. Persistent application state is stored
in the configured database and data directory.

Normalization sends prompts containing recipe text and source metadata to the
configured LLM provider. Ollama can remain local; a remote OpenAI-compatible
provider receives this content over the network. Users must assess the
provider's retention, logging, jurisdiction, and model-training policies.

AI API keys, Mealie tokens, and Food Assistant API tokens are server-side
credentials. AI keys are not returned by APIs or embedded in the review page.
Avoid placing credentials in URLs because proxies and browsers may record them.

The project does not bundle or redistribute third-party recipe collections.
Users control source synchronization and are responsible for source licenses,
terms, personal-data handling, retention, and deletion.
