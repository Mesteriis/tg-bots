from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.audit.models import AuditEvent
from tg_bot_aggregator.domain.auth.models import ApiToken
from tg_bot_aggregator.domain.bots.models import Bot
from tg_bot_aggregator.domain.destinations.models import Destination
from tg_bot_aggregator.domain.diagnostics.models import DiagnosticBotSettings
from tg_bot_aggregator.domain.discovery.models import BotDiscoveryEvent, BotDiscoverySettings
from tg_bot_aggregator.domain.operations.schemas import RuntimeSettingsRead
from tg_bot_aggregator.domain.sending.models import SendHistory
from tg_bot_aggregator.domain.templates.models import MessageTemplate


async def test_core_models_can_be_inserted(db_session: AsyncSession) -> None:
    bot = Bot(name="ops", token="123:token", username="ops_bot", telegram_bot_id=123)
    db_session.add(bot)
    await db_session.flush()

    destination = Destination(
        bot_id=bot.id,
        kind="forum_topic",
        chat_id="-100123",
        message_thread_id=42,
        title="Deployments",
    )
    template = MessageTemplate(tag="deploy", title="Deploy", text="Deployment done")
    db_session.add_all([destination, template])
    await db_session.flush()

    history = SendHistory(
        bot_id=bot.id,
        destination_id=destination.id,
        chat_id=destination.chat_id,
        message_thread_id=destination.message_thread_id,
        tag=template.tag,
        text=template.text,
        media_type="none",
        status="succeeded",
        telegram_message_id=77,
    )
    db_session.add(history)
    await db_session.commit()

    rows = (await db_session.execute(select(SendHistory))).scalars().all()

    assert len(rows) == 1
    assert rows[0].chat_id == "-100123"
    assert rows[0].message_thread_id == 42


async def test_diagnostic_settings_model_can_select_product_bot(
    db_session: AsyncSession,
) -> None:
    bot = Bot(name="diagnostics", token="123:token", username="diag_bot", telegram_bot_id=123)
    db_session.add(bot)
    await db_session.flush()

    settings = DiagnosticBotSettings(id=1, bot_id=bot.id, is_enabled=True, last_update_id=77)
    db_session.add(settings)
    await db_session.commit()

    row = (await db_session.execute(select(DiagnosticBotSettings))).scalar_one()

    assert row.bot_id == bot.id
    assert row.is_enabled is True
    assert row.last_update_id == 77


async def test_ops_automation_models_can_be_inserted(db_session: AsyncSession) -> None:
    bot = Bot(name="ops", token="123:token", username="ops_bot", telegram_bot_id=123)
    db_session.add(bot)
    await db_session.flush()

    token = ApiToken(
        name="sender",
        token_hash="hash",
        token_prefix="tga_sender",
        scopes_json=["read", "send"],
    )
    destination = Destination(
        bot_id=bot.id,
        kind="channel",
        chat_id="@ops",
        title="Ops",
        alias="ops_channel",
    )
    history = SendHistory(
        bot_id=bot.id,
        destination_id=None,
        chat_id="@ops",
        text="hello",
        media_type="none",
        status="queued",
        send_mode="queued",
        idempotency_key="send-1",
        idempotency_fingerprint="fingerprint",
        attempt_count=1,
    )
    audit = AuditEvent(
        source="api",
        action="send.text",
        status="accepted",
        api_token_id=None,
        host="127.0.0.1",
        path="/api/v1/send/text",
        method="POST",
        entity_type="send_history",
        entity_id="1",
        metadata_json={"redacted": True},
    )
    discovery_settings = BotDiscoverySettings(
        bot_id=bot.id,
        is_enabled=True,
        last_update_id=11,
    )
    db_session.add_all([token, destination, history, audit, discovery_settings])
    await db_session.flush()
    discovery_event = BotDiscoveryEvent(
        bot_id=bot.id,
        update_id=12,
        chat_id="-100",
        kind="supergroup",
        old_status="left",
        new_status="administrator",
        raw_update_json={"update_id": 12},
    )
    db_session.add(discovery_event)
    await db_session.commit()

    loaded_destination = (await db_session.execute(select(Destination))).scalars().first()
    loaded_token = (await db_session.execute(select(ApiToken))).scalar_one()
    loaded_history = (await db_session.execute(select(SendHistory))).scalars().first()
    loaded_audit = (await db_session.execute(select(AuditEvent))).scalar_one()
    loaded_discovery = (await db_session.execute(select(BotDiscoverySettings))).scalar_one()

    assert loaded_destination.alias == "ops_channel"
    assert loaded_token.scopes_json == ["read", "send"]
    assert loaded_history.send_mode == "queued"
    assert loaded_history.idempotency_key == "send-1"
    assert loaded_audit.action == "send.text"
    assert loaded_discovery.last_update_id == 11


def test_runtime_settings_read_includes_telegram_egress_fields() -> None:
    payload = RuntimeSettingsRead.model_validate(
        {
            "app_host": "127.0.0.1",
            "app_port": 8000,
            "database_url": "sqlite+aiosqlite:///:memory:",
            "redis_url": "redis://redis:6379/0",
            "telegram_api_id": None,
            "telegram_api_hash": None,
            "telegram_bot_api_base_url": "https://api.telegram.org",
            "cors_allowed_origins": ["http://localhost:8000"],
            "mcp_allowed_origins": ["http://localhost:8000"],
            "shared_media_root": "/shared/media",
            "shared_media_require_mount": False,
            "max_local_file_bytes": 2097152000,
            "telethon_session_dir": "/data/telethon",
            "diagnostic_poll_timeout_seconds": 30,
            "diagnostic_retry_delay_seconds": 5.0,
            "discovery_poll_timeout_seconds": 30,
            "discovery_retry_delay_seconds": 5.0,
            "send_retry_max_attempts": 3,
            "send_retry_delay_seconds": 1.0,
            "reliability_enabled": False,
            "send_default_mode": "sync",
            "send_global_rate_per_minute": None,
            "send_bot_rate_per_minute": None,
            "send_chat_rate_per_minute": None,
            "send_destination_rate_per_minute": None,
            "send_retry_base_delay_seconds": 1.0,
            "send_retry_max_delay_seconds": 300.0,
            "send_worker_lease_seconds": 60,
            "send_stale_lock_grace_seconds": 30,
            "send_dedupe_window_seconds": None,
            "protected_api_hosts": [],
            "policy_enabled": False,
            "rate_limit_per_minute": None,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
            "callback_enabled": False,
            "callback_url": None,
            "backup_git_repo_url": None,
            "backup_git_branch": "main",
            "backup_git_path": "tg-bots.json",
            "backup_git_service": "auto",
            "backup_git_auth_method": "token",
            "backup_git_api_base_url": None,
            "backup_git_api_token": None,
            "backup_include_secrets": False,
            "backup_schedule_enabled": False,
            "backup_schedule_interval_seconds": 86400,
            "backup_schedule_push_to_git": False,
            "telegram_egress_mode": "direct",
            "telegram_egress_enabled": False,
            "telegram_egress_provider": None,
            "telegram_egress_last_status": "disconnected",
            "telegram_egress_last_error": None,
            "telegram_egress_connected_at": None,
            "telegram_egress_last_handshake_at": None,
            "telegram_egress_last_egress_ip": None,
        }
    )

    assert payload.telegram_egress_mode == "direct"
