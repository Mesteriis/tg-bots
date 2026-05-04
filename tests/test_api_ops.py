import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base, utc_now
from tg_bot_aggregator.repositories import (
    AuditRepository,
    BotRepository,
    DiagnosticUpdateRepository,
    McpSettingsRepository,
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)


@pytest.fixture
async def ops_client() -> tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_bus = MemoryEventBus()
    app = create_app(
        Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        session_factory=session_factory,
        event_bus=event_bus,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, session_factory, event_bus
    await engine.dispose()


async def test_ops_scan_preview_apply_and_audit(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, event_bus = ops_client
    async with session_factory() as session:
        await BotRepository(session).create(name="ops", token="123:abc")
        await DiagnosticUpdateRepository(session).create(
            update_id=200,
            update_kind="message",
            chat_id="-1002",
            chat_type="supergroup",
            chat_title="Ops Two",
            message_thread_id=None,
            raw_update_json={"update_id": 200},
            created_at=utc_now(),
        )
        await session.commit()

    scan = await client.post("/api/v1/ops/scan")
    facts = await client.get("/api/v1/ops/facts")
    recommendations = await client.get("/api/v1/ops/recommendations")
    recommendation_id = recommendations.json()[0]["id"]
    preview = await client.post(f"/api/v1/ops/recommendations/{recommendation_id}/preview")
    applied = await client.post(f"/api/v1/ops/recommendations/{recommendation_id}/apply")
    runs = await client.get("/api/v1/ops/action-runs")

    assert scan.status_code == 200
    assert scan.json() == {"facts_created": 1, "recommendations_created": 1}
    assert facts.status_code == 200
    assert facts.json()[0]["chat_id"] == "-1002"
    assert recommendations.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["diff"]["operation"] == "create"
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert runs.status_code == 200
    assert runs.json()[0]["status"] == "succeeded"

    async with session_factory() as session:
        actions = [row.action for row in await AuditRepository(session).list(limit=10)]
        action_runs = await OpsActionRunRepository(session).list()

    assert "ops.scan" in actions
    assert "ops.action.previewed" in actions
    assert "ops.action.applied" in actions
    assert [run.action_type for run in action_runs[:2]] == ["apply", "preview"]
    assert (await event_bus.latest()).event_type == "ops.action.applied"


async def test_ops_rules_update_run_pause_resume_emit_audit_and_events(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, event_bus = ops_client
    scan = await client.post("/api/v1/ops/scan")
    rules = await client.get("/api/v1/ops/rules")
    rule_id = rules.json()[0]["id"]

    updated = await client.patch(
        f"/api/v1/ops/rules/{rule_id}",
        json={"mode": "suggest_only", "is_enabled": True},
    )
    ran = await client.post(f"/api/v1/ops/rules/{rule_id}/run")
    paused = await client.post(f"/api/v1/ops/rules/{rule_id}/pause")
    resumed = await client.post(f"/api/v1/ops/rules/{rule_id}/resume")

    assert scan.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["is_enabled"] is True
    assert ran.status_code == 200
    assert ran.json()["rule_id"] == rule_id
    assert paused.status_code == 200
    assert paused.json()["is_paused"] is True
    assert resumed.status_code == 200
    assert resumed.json()["is_paused"] is False
    assert (await event_bus.latest()).event_type == "ops.rule.resumed"

    async with session_factory() as session:
        actions = [row.action for row in await AuditRepository(session).list(limit=10)]

    assert "ops.rule.updated" in actions
    assert "ops.rule.ran" in actions
    assert "ops.rule.paused" in actions
    assert "ops.rule.resumed" in actions


async def test_ops_dismiss_recommendation_emits_audit_and_event(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, event_bus = ops_client
    async with session_factory() as session:
        await BotRepository(session).create(name="ops", token="123:abc")
        await DiagnosticUpdateRepository(session).create(
            update_id=201,
            update_kind="message",
            chat_id="-1003",
            chat_type="supergroup",
            chat_title="Ops Three",
            raw_update_json={"update_id": 201},
            created_at=utc_now(),
        )
        await session.commit()

    await client.post("/api/v1/ops/scan")
    recommendations = await client.get("/api/v1/ops/recommendations")
    recommendation_id = recommendations.json()[0]["id"]
    dismissed = await client.post(f"/api/v1/ops/recommendations/{recommendation_id}/dismiss")

    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert (await event_bus.latest()).event_type == "ops.recommendation.dismissed"
    async with session_factory() as session:
        actions = [row.action for row in await AuditRepository(session).list(limit=5)]
    assert "ops.recommendation.dismissed" in actions


async def test_ops_mcp_coverage_endpoint_shape(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, _ = ops_client
    async with session_factory() as session:
        await McpSettingsRepository(session).upsert(
            enabled_tools_json=["list_bots", "list_ops_facts"]
        )
        await session.commit()

    response = await client.get("/api/v1/ops/mcp-coverage")

    assert response.status_code == 200
    payload = response.json()
    domains = {row["domain"] for row in payload["rows"]}
    assert {"telegram_ops", "send", "reliability", "operations_backup"} <= domains
    telegram_ops = next(row for row in payload["rows"] if row["domain"] == "telegram_ops")
    assert "list_ops_facts" in telegram_ops["mcp_read_tools"]
    assert isinstance(payload["missing_enabled_tools"], list)
    assert isinstance(payload["missing_catalog_tools"], list)


async def test_get_ops_rules_is_read_only_when_empty(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, _ = ops_client

    response = await client.get("/api/v1/ops/rules")

    assert response.status_code == 200
    assert response.json() == []
    async with session_factory() as session:
        assert await OpsAutomationRuleRepository(session).list() == []


async def test_get_ops_mcp_coverage_does_not_create_settings_row(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, _ = ops_client

    response = await client.get("/api/v1/ops/mcp-coverage")

    assert response.status_code == 200
    enabled_tools = {
        tool
        for row in response.json()["rows"]
        for tool in row["enabled"]
    }
    assert "send_text" not in enabled_tools
    assert "create_api_token" not in enabled_tools
    assert "preview_ops_action" not in enabled_tools
    async with session_factory() as session:
        assert await McpSettingsRepository(session).get() is None


async def test_preview_unknown_recommendation_returns_404(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, _, _ = ops_client

    response = await client.post("/api/v1/ops/recommendations/999/preview")

    assert response.status_code == 404


async def test_invalid_rule_update_returns_400(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, _, _ = ops_client
    await client.post("/api/v1/ops/scan")
    rules = await client.get("/api/v1/ops/rules")
    rule_id = rules.json()[0]["id"]

    response = await client.patch(
        f"/api/v1/ops/rules/{rule_id}",
        json={"mode": "auto_apply", "risk_limit": "medium"},
    )

    assert response.status_code == 400


async def test_get_operations_settings_is_read_only_when_empty(
    ops_client: tuple[httpx.AsyncClient, async_sessionmaker, MemoryEventBus],
) -> None:
    client, session_factory, _ = ops_client

    response = await client.get("/api/v1/operations/settings")

    assert response.status_code == 200
    async with session_factory() as session:
        assert await RuntimeSettingsRepository(session).get() is None
        assert await RuntimeAdvancedSettingsRepository(session).get() is None
