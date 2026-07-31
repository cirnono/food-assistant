# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Targeted queued-item processing and rejected-item restoration to the review
  API and UI.
- Dry-run-first duplicate import resolution with structured audit fields.

### Fixed

- Treat skipped duplicate items as terminal when calculating job completion.

## [0.21.1] - 2026-08-01

### Added

- Safe reconciliation CLI for verified, already-existing managed Mealie recipes.
- Regression coverage for paginated entity lookup and unique-conflict recovery.

### Fixed

- Docker Secret host files can be configured outside the repository with
  `*_HOST_FILE` variables.
- Mealie category, tag, food, and unit conflicts recover through cached,
  paginated entity collections without duplicate creation.

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

[Unreleased]: https://github.com/cirnono/food-assistant/compare/v0.21.1...HEAD
[0.21.1]: https://github.com/cirnono/food-assistant/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/cirnono/food-assistant/releases/tag/v0.21.0
