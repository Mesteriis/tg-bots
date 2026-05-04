# Contributing

Thanks for considering a contribution.

## Development

Use Python 3.11 or newer.

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
```

## Pull Requests

- Keep changes focused.
- Add or update tests for behavior changes.
- Do not commit `.env`, SQLite databases, Telethon sessions, bot tokens, or API tokens.
- Document public API, deployment, or configuration changes.

## Security

This project intentionally supports unauthenticated localhost/LAN use. Treat deployments as trusted-network services unless you add an explicit auth layer.
