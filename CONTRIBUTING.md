# Contributing

Thanks for considering a contribution.

## Development

Use Python 3.11 or newer.

```bash
python -m pip install -e ".[dev]"
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m pytest
```

## Pull Requests

- Keep changes focused.
- Add or update tests for behavior changes.
- Do not commit `.env`, SQLite databases, Telethon sessions, bot tokens, or API tokens.
- Document public API, deployment, or configuration changes.

## Security

This project intentionally supports unauthenticated localhost/LAN use. Treat deployments as trusted-network services unless you add an explicit auth layer.
