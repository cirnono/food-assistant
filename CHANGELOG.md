# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.24.0] - 2026-08-02

### Added

- Owner-scoped persistent cooking sessions with stable Mealie recipe snapshots,
  step navigation, checked ingredients, and cooking-history completion.
- Durable UTC-deadline cooking timers with pause, resume, recovery, and an
  eight-timer safety limit without per-second database writes.
- Responsive `/cook` Surface/mobile interface with local countdowns and
  explicit completion and cancellation confirmation.
- Lightweight authenticated active-cooking state and native Home Assistant
  cooking sensors, actions, scripts, and conditional dashboard examples.

### Changed

- Home Assistant aggregate state now includes a lightweight `active_cooking`
  summary without invoking another recommendation or Mealie request.
- Cooking completion returns only a read-only inventory-consumption preview;
  pantry quantities are never changed automatically.

## [0.23.0] - 2026-08-02

### Added

- Persistent, owner-scoped Home Assistant recommendation selection state.
- Authenticated aggregate state, next-selection, mark-cooked, and refresh APIs.
- Native Home Assistant package and responsive Lovelace kitchen view examples.

### Changed

- Successful Mealie recipe details now use a configurable six-hour cache by
  default, with explicit refresh support.

### Fixed

- Reuse a lifespan-managed Mealie connection pool for recommendation requests.
- Isolate per-recipe detail failures and cache successful and failed detail
  reads across recommendation requests.
- Bound and de-duplicate Mealie pagination to prevent malformed metadata from
  causing repeated or unbounded page reads.

## [0.22.0] - 2026-08-02

### Added

- Responsive pantry management and explainable recipe recommendation pages.
- Pantry lifecycle fields, low-stock reporting, and consume/restock/open actions.
- User-managed ingredient aliases and cooking history APIs.
- Recommendation v2 with complete Mealie pagination, bounded detail concurrency,
  expiry priority, recent-cooking penalty, and transparent score reasons.
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

[Unreleased]: https://github.com/cirnono/food-assistant/compare/v0.24.0...HEAD
[0.24.0]: https://github.com/cirnono/food-assistant/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/cirnono/food-assistant/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/cirnono/food-assistant/compare/v0.21.1...v0.22.0
[0.21.1]: https://github.com/cirnono/food-assistant/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/cirnono/food-assistant/releases/tag/v0.21.0
