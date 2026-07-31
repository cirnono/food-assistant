## Summary

Describe the outcome and compatibility impact.

## Verification

- [ ] `python -m compileall -q app`
- [ ] `pytest`
- [ ] `ruff check .`
- [ ] `docker compose config --quiet`

## Safety

- [ ] No tokens, authorization headers, private hosts, databases, recipe source
      content, clones, runtime data, logs, or backups are included.
- [ ] External integrations are mocked in tests.
- [ ] Documentation and changelog are updated when behavior changes.
