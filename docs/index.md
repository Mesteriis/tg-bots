# Telegram Bot Aggregator

Local operator console for Telegram bot sending workflows: bots, destinations, templates,
send history, reliability controls, MCP tools, backups, and Telegram connectivity.

## Dashboard

![Operator tour](screenshots/operator-tour.gif)

## Core Workflow

1. Add a Bot API token.
2. Save a destination with chat ID, alias, or forum thread ID.
3. Create a tagged template or write a one-off message.
4. Run preflight, send immediately, or enqueue through the reliability layer.

![Sending workflow](screenshots/send-workflow.png)

## Main Screens

![Bots overview](screenshots/bots-overview.png)

![Reliability overview](screenshots/reliability-overview.png)

![Configuration overview](screenshots/settings-overview.png)

## Documentation

- [Repository README](../README.md)
- [Deployment notes](deployment/rnet-proxmox.md)
- [Design specs](superpowers/specs/)
