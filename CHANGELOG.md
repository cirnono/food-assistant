# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.21.0] - 2026-07-31

### Added

- Pluggable Ollama and OpenAI-compatible structured-chat providers.
- Secure authenticated LLM status and connection-test endpoints.
- Read-only AI configuration status in the review interface.
- Safe environment and Docker Secrets examples.
- Provider, security, batch, recipe-repair, timer, API, and idempotency tests.
- Public release documentation, security policy, and CI configuration.

### Changed

- Unified LLM error handling and infrastructure-outage classification.
- Replaced deployment-specific defaults with portable self-hosted defaults.
- Preserved legacy `OLLAMA_*` variables with deprecation logging.

### Security

- Redacted provider credentials from errors and status responses.
- Excluded local secrets, databases, runtime data, source clones, logs, and
  backups from the public repository.

[Unreleased]: https://github.com/OWNER/food-assistant/compare/v0.21.0...HEAD
[0.21.0]: https://github.com/OWNER/food-assistant/releases/tag/v0.21.0
