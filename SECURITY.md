# Security Policy

## Supported Versions

Security fixes target the `main` branch until versioned releases are introduced.

## Reporting

Do not open public issues for vulnerabilities that include tokens, private URLs, or deployment secrets. Report privately through the repository owner or the internal Gitea contact for this project.

## Deployment Warning

The app is designed for trusted local-network operation. Bot tokens are stored in SQLite as plain text by product decision. Protected public hosts should use permanent API tokens and nginx host routing, but this is not a full multi-user auth model.
