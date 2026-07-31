# Contributing

Thank you for contributing. Open an issue before a large behavioral change so
compatibility expectations can be agreed first.

## Development

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python3 -m compileall -q app
pytest
ruff check .
docker compose config --quiet
```

Keep changes focused and preserve existing APIs unless a compatibility layer is
included. Mock Ollama, Mealie, and remote providers in tests. Do not contribute
recipe corpora, cloned source repositories, databases, images, logs, backups,
tokens, private hostnames, or internal addresses.

Use clear commits and update tests and documentation with behavior changes. By
submitting a contribution, you agree that it may be distributed under the MIT
License.
