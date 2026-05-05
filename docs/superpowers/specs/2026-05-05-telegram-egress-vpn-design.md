# Telegram Egress VPN Design

**Date:** 2026-05-05

**Status:** Draft for review

**Goal:** Add an optional outbound VPN layer for Telegram-facing traffic so the service can continue reaching Telegram APIs and MTProto from blocked networks, without forcing the entire local admin stack through the tunnel.

## Problem

The product depends on multiple outbound Telegram paths:

- Bot API calls from `app`
- queued send execution from `worker`
- local Telegram Bot API server to Telegram upstream
- Telethon/MTProto analytics
- diagnostic polling bot
- automatic chat discovery bot

In hostile or filtered networks, direct access to Telegram is unreliable or blocked. A production-safe solution must restore Telegram reachability while preserving:

- local dashboard access
- SQLite/PostgreSQL access
- Redis access
- restore/backup flows
- predictable observability and operator control

The VPN layer is not a general-purpose remote access feature. It is a controlled egress mechanism for Telegram connectivity.

## Scope

Version 1 includes:

- Explicit egress modes:
  - `direct`
  - `wireguard`
  - `openvpn`
- A dedicated VPN sidecar/gateway container for Telegram-facing traffic.
- Runtime settings and dashboard controls for provider selection and tunnel lifecycle.
- File-backed secret storage for VPN credentials and configs.
- Health/status surface for tunnel state and Telegram reachability.
- Compose support for routing Telegram-facing services through the VPN sidecar.

Out of scope for version 1:

- Xray implementation
- full device-level VPN for the host or LXC
- per-bot or per-request egress routing
- multiple simultaneous VPN profiles
- automatic provider failover
- smart geographic routing
- arbitrary SOCKS/HTTP proxy chains

Roadmap item:

- `xray` as a future provider after WireGuard/OpenVPN stabilization

## Design Summary

The recommended architecture is a **Telegram egress sidecar**. Telegram-related containers share the network namespace or explicit network path of the VPN container, while the rest of the stack remains on ordinary Docker networking.

Services that should use Telegram egress:

- `app`
- `worker`
- `telegram-bot-api`
- `diagnostic-bot`
- `discovery-bot`

Services that should remain outside the tunnel:

- browser admin UI entrypoint
- Redis
- SQLite/PostgreSQL
- backup/restore control paths
- local-only administration endpoints

This avoids turning the entire app stack into a VPN appliance and keeps local operations debuggable.

## Alternatives Considered

### 1. VPN sidecar/gateway for Telegram-facing services

Recommended.

Pros:

- clean network boundary
- minimal blast radius
- explicit operator control
- works for Bot API and MTProto paths together
- composes well with Docker and existing runtime settings

Cons:

- requires container/network orchestration work
- requires clear status reporting and secret management

### 2. Only route `telegram-bot-api` through VPN

Rejected for version 1.

Pros:

- smallest network change

Cons:

- insufficient for Telethon/MTProto
- diagnostics/discovery may still fail
- creates partial protection and operator confusion

### 3. Global VPN for the whole stack

Rejected.

Pros:

- simple mental model

Cons:

- drags admin UI and infra paths through the tunnel
- harder to debug
- unnecessary coupling between local operations and Telegram connectivity

## Architecture

### Container Model

Add one new service:

- `telegram-egress`

Responsibilities:

- owns VPN process lifecycle
- exposes health/readiness state
- optionally exposes current egress IP and handshake metadata
- serves as the network path for Telegram-facing containers

Provider runtime inside the sidecar:

- `wireguard` mode
- `openvpn` mode

Version 1 recommendation:

- one sidecar image with provider-specific entrypoint logic
- provider selected by runtime settings and file-backed config

### Network Model

Preferred model:

- Telegram-facing containers share the VPN sidecar network namespace
- local service-to-service traffic remains on Docker internal networks

Practical compose implementation options:

1. `network_mode: "service:telegram-egress"` for the Telegram-facing containers
2. a custom routing arrangement where the sidecar becomes the default gateway

Recommendation for version 1:

- use `network_mode: "service:telegram-egress"` where feasible
- keep the design explicit and boring rather than clever

Implication:

- any container using `service:telegram-egress` must be designed with that networking model in mind
- health and observability need to move up to the application layer because individual container ports and interfaces become less transparent

## Provider Abstraction

Introduce a small provider abstraction in the operations/infra layer.

Required provider interface:

- `validate_config()`
- `connect()`
- `disconnect()`
- `restart()`
- `status()`
- `egress_ip()`
- `telegram_reachability_check()`

Version 1 providers:

- `WireGuardProvider`
- `OpenVpnProvider`

Roadmap provider:

- `XrayProvider`

The provider abstraction should stay narrow. It is not a general network orchestration framework.

## Settings Model

### Runtime Metadata in SQLite

Store only non-secret operational metadata in runtime settings, for example:

- `telegram_egress_mode`: `direct | wireguard | openvpn`
- `telegram_egress_enabled`: `bool`
- `telegram_egress_provider`: `wireguard | openvpn | null`
- `telegram_egress_last_status`: `connected | disconnected | degraded | failed`
- `telegram_egress_last_error`
- `telegram_egress_connected_at`
- `telegram_egress_last_handshake_at`
- `telegram_egress_last_egress_ip`

These fields belong in runtime settings or a closely related operations model, not in ad hoc files.

### File-Backed Secret Store

Secret material must not be stored in SQLite.

Store secrets/config files under app data, for example:

```text
/data/telegram-egress/
  provider.json
  wireguard/
    profile.conf
  openvpn/
    profile.ovpn
    auth.txt
```

Version 1 file storage requirements:

- atomic writes
- strict permissions
- readable diagnostics without leaking secret values
- validation before activation

Secret material includes:

- WireGuard private keys
- WireGuard peer config
- OpenVPN profiles
- OpenVPN credentials
- future Xray outbound config

## Dashboard UX

Add a `Telegram connectivity` section under:

- `Настройки -> Инфраструктура`

UI content:

- mode switch:
  - `direct`
  - `wireguard`
  - `openvpn`
- provider-specific config summary
- current tunnel state
- connected since
- last handshake
- current egress IP
- Bot API reachability
- MTProto reachability
- last error

Actions:

- `Connect`
- `Disconnect`
- `Restart`
- `Check connectivity`
- `Upload/replace config`
- `Remove config`

Version 1 UX rules:

- do not show secret values after save
- show clear degraded states
- disable provider activation when config is missing or invalid
- show explicit warning when in `direct` mode and connectivity checks fail

## REST API

Add operations endpoints under `/api/v1/operations`, for example:

- `GET /api/v1/operations/telegram-egress`
- `PATCH /api/v1/operations/telegram-egress`
- `POST /api/v1/operations/telegram-egress/connect`
- `POST /api/v1/operations/telegram-egress/disconnect`
- `POST /api/v1/operations/telegram-egress/restart`
- `POST /api/v1/operations/telegram-egress/check`
- `POST /api/v1/operations/telegram-egress/config`
- `DELETE /api/v1/operations/telegram-egress/config`

Response model should expose:

- configured provider
- enabled/disabled
- effective mode
- tunnel state
- egress IP
- last handshake
- last error
- provider config presence
- Bot API reachability
- MTProto reachability

The API should not return raw config secrets.

## Health and Reachability

Connectivity checks must distinguish at least these cases:

- VPN disabled, direct path works
- VPN disabled, direct path blocked
- VPN enabled, tunnel up, Telegram reachable
- VPN enabled, tunnel up, Telegram still unreachable
- VPN enabled, provider failed to connect
- provider config missing/invalid

Checks to perform:

- generic outbound IP check
- Telegram Bot API check
- MTProto check

Recommendation:

- keep checks explicit and bounded with timeouts
- avoid background loops that spam external endpoints

## Compose and Deployment

Version 1 requires updates to:

- `docker-compose.yml`
- `deploy/docker-compose.lxc.yml`
- `.env.example`
- deployment docs

Expected env/config additions:

- `TELEGRAM_EGRESS_MODE=direct|wireguard|openvpn`
- `TELEGRAM_EGRESS_STATE_DIR=/data/telegram-egress`

The stack must still work in plain `direct` mode without the VPN sidecar being active.

That means:

- local development should remain zero-friction
- deploys without VPN config should still boot normally
- the dashboard should truthfully report `direct` mode

## Security Constraints

VPN config is highly sensitive.

Required controls:

- file-backed storage with restrictive permissions
- no logging of private keys, passwords, or full profiles
- no raw secret echo in API responses
- secret redaction in backup/export paths by default
- explicit operator warning before deleting active config

Backup behavior:

- VPN secret files must not be included in normal JSON backups
- metadata may be backed up
- future secret backup support, if any, must be explicit and separately reviewed

## Observability

Add useful, bounded observability:

- current provider
- tunnel state
- last connect/disconnect timestamps
- last handshake
- egress IP
- last reachability check results
- last provider error

Operator-facing dashboard should prefer summarized state over raw process logs.

## Testing Strategy

Unit tests:

- provider selection
- config validation
- secret file write/read behavior
- status model mapping
- redaction behavior

Integration tests:

- operations API for mode/config lifecycle
- direct mode status
- missing-config behavior
- failed-provider startup behavior

Manual validation:

1. start stack in `direct` mode
2. verify Bot API works without VPN
3. enable WireGuard with valid config
4. verify status becomes connected
5. verify Telegram Bot API calls still work
6. verify MTProto status/check path still works
7. disconnect VPN and verify degraded state is visible
8. switch to OpenVPN and repeat

Version 1 does not require fully emulating blocked-RU traffic in CI.

## Rollout Plan

Recommended implementation slices:

1. file-backed config store and runtime metadata
2. provider abstraction with `direct` + stubbed status path
3. WireGuard provider
4. dashboard status and control UI
5. OpenVPN provider
6. compose/deploy integration
7. docs and operator validation

This keeps the first working slice small and testable.

## Roadmap

Future work after version 1:

- `xray` provider
- provider failover policies
- separate egress routing for different Telegram workloads
- automatic recovery/backoff
- metrics panel for long-term tunnel stability

## Design Self-Review

Placeholder scan:

- no blocking placeholders remain

Internal consistency:

- provider scope, storage model, and UI all assume VPN is an outbound egress feature, not a full host VPN

Scope check:

- version 1 is intentionally limited to WireGuard/OpenVPN plus dashboard control and health

Ambiguity check:

- Xray is explicitly roadmap-only, not version 1
- secret storage is explicitly file-backed, not SQLite-backed
