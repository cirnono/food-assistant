# Open-source release work log

This file records resumable, non-secret project state. Never record environment
values, tokens, API keys, request headers, private hostnames, or upstream response
bodies here.

## Current baseline

- Target release: `0.23.0`
- Starting application version: `0.20.1`
- Branch: `main`
- Existing phase commit: `18b05c9 chore: initialize public repository hygiene`
- Preserved pre-existing work:
  - `app/review_ui.py`: import-item list request adds `limit=1000`
  - `app/llm/__init__.py`: provider package placeholder
  - ignored local UI backup file remains on disk and must not be deleted

## Phase status

- Phase 0 — audit: validated against the live tree; report is tracked in the
  phase-1 baseline commit.
- Phase 1 — repository hygiene: complete in commit `18b05c9`.
- Phase 2 — provider abstraction: complete in commit `63931ac`.
- Phase 3 — secure status/test API and review UI panel: implemented and
  complete in commit `ec7df8a`.
- Phase 4 — safe environment and Compose examples: implemented and validated;
  complete in commit `0a5a607`.
- Phase 5 — test/lint toolchain and regression coverage: implemented and
  complete in commit `b140c5a`.
- Phase 6 — public documentation, license, changelog, security and contributing
  files: complete in commit `9f8399c`.
- Phase 7 — GitHub Actions and contribution templates: complete in commit
  `8bb12b3`.
- Phase 8 — final security, version, build, test, and smoke checks: complete;
  release commit pending.

## Resume point

Create the phase-8 release commit, then follow the documented GitHub publishing
commands when the repository owner is ready. Do not push automatically.
