from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.diagnostics.repository import DiagnosticUpdateRepository
from tg_bot_aggregator.domain.discovery.repository import BotDiscoveryEventRepository
from tg_bot_aggregator.domain.mcp.repository import McpCoverageSnapshotRepository
from tg_bot_aggregator.domain.ops.repository import (
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)
from tg_bot_aggregator.domain.ops.service import (
    McpCoverageService,
    TelegramOpsError,
    TelegramOpsService,
    build_destination_diff,
    normalize_destination_kind,
)
from tg_bot_aggregator.models import Base, Destination, OpsFact, utc_now
from tg_bot_aggregator.schemas import McpCoverageRead


@pytest.mark.asyncio
async def test_ops_fact_recommendation_rule_and_action_run_repositories(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    facts = OpsFactRepository(db_session)
    recommendations = OpsRecommendationRepository(db_session)
    rules = OpsAutomationRuleRepository(db_session)
    runs = OpsActionRunRepository(db_session)

    fact = await facts.upsert_fact(
        fact_type="chat_seen",
        bot_id=bot.id,
        chat_id="-1001",
        message_thread_id=None,
        source="diagnostic_update",
        title="Ops Chat",
        username="ops_chat",
        kind="supergroup",
        status="active",
        confidence=100,
        payload_json={"chat_id": "-1001", "token": "redacted"},
    )
    recommendation = await recommendations.create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        fact_ids_json=[fact.id],
        title="Create destination Ops Chat",
        reason="Chat was observed but no destination exists.",
        diff_json={"create": {"chat_id": "-1001", "kind": "supergroup"}},
        action_payload_json={"bot_id": bot.id, "chat_id": "-1001"},
    )
    rule = await rules.upsert_by_key(
        "create_destination_from_seen_chat",
        title="Create destinations from observed chats",
        mode="suggest_only",
        is_enabled=True,
        is_paused=False,
        risk_limit="low",
        config_json={},
    )
    action_run = await runs.create(
        recommendation_id=recommendation.id,
        rule_id=rule.id,
        action_type="preview",
        source="dashboard",
        actor="local",
        status="succeeded",
        preview_diff_json=recommendation.diff_json,
        request_payload_json={"recommendation_id": recommendation.id},
        result_json={"status": "previewed"},
        rollback_hint="No data was changed.",
        finished_at=utc_now(),
    )
    await db_session.commit()

    assert (await facts.list())[0].chat_id == "-1001"
    assert (await recommendations.list(status="open"))[0].id == recommendation.id
    assert (await rules.list())[0].rule_key == "create_destination_from_seen_chat"
    assert (await runs.list())[0].id == action_run.id


@pytest.mark.asyncio
async def test_ops_action_run_repository_updates_and_marks_status(
    db_session: AsyncSession,
) -> None:
    runs = OpsActionRunRepository(db_session)
    action_run = await runs.create(
        action_type="apply",
        source="dashboard",
        actor="local",
        status="running",
        request_payload_json={"recommendation_id": 1},
    )

    updated = await runs.update(
        action_run.id,
        preview_diff_json={"create": {"chat_id": "-1001"}},
        rollback_hint="Delete created destination.",
    )
    succeeded = await runs.mark_succeeded(
        updated,
        result_json={"destination_id": 10},
    )
    await db_session.commit()
    loaded = await runs.get(action_run.id)

    assert loaded is not None
    assert updated.preview_diff_json == {"create": {"chat_id": "-1001"}}
    assert succeeded.status == "succeeded"
    assert succeeded.error_message is None
    assert succeeded.result_json == {"destination_id": 10}
    assert succeeded.finished_at is not None
    assert loaded.status == "succeeded"


@pytest.mark.asyncio
async def test_ops_action_run_repository_marks_failed(
    db_session: AsyncSession,
) -> None:
    runs = OpsActionRunRepository(db_session)
    action_run = await runs.create(
        action_type="apply",
        source="dashboard",
        actor="local",
        status="running",
        request_payload_json={"recommendation_id": 1},
    )

    failed = await runs.mark_failed(
        action_run,
        error_message="apply failed",
        result_json={"rollback": "not needed"},
    )
    await db_session.commit()
    loaded = await runs.get(action_run.id)

    assert loaded is not None
    assert failed.status == "failed"
    assert failed.error_message == "apply failed"
    assert failed.result_json == {"rollback": "not needed"}
    assert failed.finished_at is not None
    assert loaded.status == "failed"


@pytest.mark.asyncio
async def test_ops_action_run_repository_rejects_terminal_status_overwrite(
    db_session: AsyncSession,
) -> None:
    runs = OpsActionRunRepository(db_session)
    action_run = await runs.create(
        action_type="apply",
        source="dashboard",
        actor="local",
        status="running",
    )
    succeeded = await runs.mark_succeeded(action_run, result_json={"destination_id": 10})

    with pytest.raises(ValueError, match="already terminal"):
        await runs.mark_failed(succeeded, error_message="late failure")

    loaded = await runs.get(action_run.id)
    assert loaded is not None
    assert loaded.status == "succeeded"
    assert loaded.error_message is None


@pytest.mark.asyncio
async def test_ops_action_run_repository_update_rejects_terminal_rows(
    db_session: AsyncSession,
) -> None:
    runs = OpsActionRunRepository(db_session)
    action_run = await runs.create(
        action_type="apply",
        source="dashboard",
        actor="local",
        status="running",
    )
    await runs.mark_succeeded(action_run, result_json={"destination_id": 10})

    with pytest.raises(ValueError, match="already terminal"):
        await runs.update(action_run.id, status="failed", error_message="late failure")

    loaded = await runs.get(action_run.id)
    assert loaded is not None
    assert loaded.status == "succeeded"
    assert loaded.error_message is None
    assert loaded.result_json == {"destination_id": 10}


@pytest.mark.asyncio
async def test_ops_fact_upsert_reuses_nullable_thread_identity(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    facts = OpsFactRepository(db_session)

    first = await facts.upsert_fact(
        fact_type="chat_seen",
        bot_id=bot.id,
        chat_id="-1001",
        message_thread_id=None,
        source="diagnostic_update",
        title="Ops Chat",
        status="active",
        confidence=90,
        payload_json={"version": 1},
    )
    second = await facts.upsert_fact(
        fact_type="chat_seen",
        bot_id=bot.id,
        chat_id="-1001",
        message_thread_id=None,
        source="diagnostic_update",
        title="Ops Chat Updated",
        status="active",
        confidence=95,
        payload_json={"version": 2},
    )
    await db_session.commit()

    rows = await facts.list()
    assert second.id == first.id
    assert len(rows) == 1
    assert rows[0].title == "Ops Chat Updated"
    assert rows[0].confidence == 95


@pytest.mark.asyncio
async def test_ops_fact_identity_key_enforces_sqlite_uniqueness_with_null_thread(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    values = {
        "identity_key": "same-identity",
        "fact_type": "chat_seen",
        "bot_id": bot.id,
        "chat_id": "-1001",
        "message_thread_id": None,
        "source": "diagnostic_update",
        "status": "active",
        "confidence": 100,
    }
    db_session.add_all([OpsFact(**values), OpsFact(**values)])

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_mcp_coverage_snapshot_repository_persists_latest(
    db_session: AsyncSession,
) -> None:
    snapshots = McpCoverageSnapshotRepository(db_session)

    first = await snapshots.create(
        matrix_json={"tools": {"send_text": {"covered": False}}},
        missing_required_tools_json=["send_text"],
        warnings_json=["missing send_text"],
    )
    second = await snapshots.create(
        matrix_json={"tools": {"send_text": {"covered": True}}},
        missing_required_tools_json=[],
        warnings_json=[],
    )
    await db_session.commit()

    latest = await snapshots.latest()

    assert first.id != second.id
    assert latest is not None
    assert latest.id == second.id
    assert latest.matrix_json == {"tools": {"send_text": {"covered": True}}}


@pytest.mark.asyncio
async def test_ops_scan_creates_destination_recommendation_from_diagnostic_update(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=100,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        chat_username="ops_chat",
        message_thread_id=77,
        is_topic_message=True,
        raw_update_json={"update_id": 100, "token": "123:secret"},
    )
    service = TelegramOpsService(db_session)

    result = await service.scan(source="test")
    await db_session.commit()
    facts = await OpsFactRepository(db_session).list()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert result == {"facts_created": 1, "recommendations_created": 1}
    assert facts[0].bot_id is None
    assert facts[0].kind == "forum_topic"
    assert facts[0].payload_json == {"update_id": 100, "token": "[REDACTED]"}
    assert recommendations[0].bot_id == bot.id
    assert recommendations[0].recommendation_type == "create_destination_from_seen_chat"
    assert recommendations[0].risk == "low"
    assert recommendations[0].diff_json["operation"] == "create"
    assert recommendations[0].diff_json["after"] == {
        "bot_id": bot.id,
        "chat_id": "-1001",
        "message_thread_id": 77,
        "kind": "forum_topic",
        "title": "Ops Chat",
        "username": "ops_chat",
        "is_active": True,
    }
    assert recommendations[0].action_payload_json == {
        "bot_id": bot.id,
        "chat_id": "-1001",
        "message_thread_id": 77,
        "kind": "forum_topic",
        "title": "Ops Chat",
        "username": "ops_chat",
        "is_active": True,
    }


@pytest.mark.asyncio
async def test_ops_scan_uses_discovery_event_bot_id_instead_of_first_active_bot(
    db_session: AsyncSession,
) -> None:
    first_bot = await BotRepository(db_session).create(name="first", token="123:first")
    discovered_bot = await BotRepository(db_session).create(name="discovered", token="123:bot")
    await BotDiscoveryEventRepository(db_session).create(
        bot_id=discovered_bot.id,
        update_id=200,
        chat_id="-1002",
        kind="supergroup",
        old_status="left",
        new_status="administrator",
        raw_update_json={
            "update_id": 200,
            "my_chat_member": {
                "chat": {
                    "id": -1002,
                    "type": "supergroup",
                    "title": "Discovered Chat",
                    "username": "discovered_chat",
                },
                "new_chat_member": {"status": "administrator"},
            },
        },
    )

    result = await TelegramOpsService(db_session).scan(source="test")
    await db_session.commit()
    facts = await OpsFactRepository(db_session).list()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert result == {"facts_created": 1, "recommendations_created": 1}
    assert facts[0].bot_id == discovered_bot.id
    assert recommendations[0].bot_id == discovered_bot.id
    assert recommendations[0].bot_id != first_bot.id
    assert recommendations[0].action_payload_json["title"] == "Discovered Chat"


@pytest.mark.asyncio
async def test_destination_chat_thread_identity_is_unique(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    destinations = DestinationRepository(db_session)
    await destinations.create(
        bot_id=bot.id,
        kind="supergroup",
        chat_id="-1001",
        message_thread_id=None,
    )

    with pytest.raises(IntegrityError):
        await destinations.create(
            bot_id=bot.id,
            kind="supergroup",
            chat_id="-1001",
            message_thread_id=None,
        )


def test_normalize_destination_kind_prefers_forum_topic_for_thread() -> None:
    assert normalize_destination_kind("supergroup", 77) == "forum_topic"
    assert normalize_destination_kind("channel", None) == "channel"
    assert normalize_destination_kind("unexpected", None) == "group"
    assert normalize_destination_kind(None, None) == "group"


def test_build_destination_diff_is_stable_and_human_readable() -> None:
    diff = build_destination_diff(
        before=None,
        after={
            "bot_id": 1,
            "chat_id": "-1001",
            "message_thread_id": 77,
            "kind": "forum_topic",
            "title": "Ops Chat",
            "username": "ops_chat",
            "is_active": True,
        },
    )

    assert list(diff) == ["operation", "before", "after", "changed"]
    assert diff["operation"] == "create"
    assert diff["before"] is None
    assert diff["after"]["chat_id"] == "-1001"
    assert diff["changed"] == {
        "bot_id": {"before": None, "after": 1},
        "chat_id": {"before": None, "after": "-1001"},
        "message_thread_id": {"before": None, "after": 77},
        "kind": {"before": None, "after": "forum_topic"},
        "title": {"before": None, "after": "Ops Chat"},
        "username": {"before": None, "after": "ops_chat"},
        "is_active": {"before": None, "after": True},
    }

    update_diff = build_destination_diff(
        before={
            "bot_id": 1,
            "chat_id": "-1001",
            "message_thread_id": None,
            "kind": "supergroup",
            "title": "Old",
            "username": None,
            "is_active": True,
        },
        after={
            "bot_id": 1,
            "chat_id": "-1001",
            "message_thread_id": 77,
            "kind": "forum_topic",
            "title": "Ops Chat",
            "username": None,
            "is_active": True,
        },
    )

    assert update_diff["operation"] == "update"
    assert update_diff["changed"] == {
        "message_thread_id": {"before": None, "after": 77},
        "kind": {"before": "supergroup", "after": "forum_topic"},
        "title": {"before": "Old", "after": "Ops Chat"},
    }


@pytest.mark.asyncio
async def test_ops_scan_creates_update_recommendation_for_metadata_drift(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    destination = await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="supergroup",
        chat_id="-1001",
        title="Old Chat",
        username="old_chat",
        is_active=True,
    )
    await DiagnosticUpdateRepository(db_session).create(
        update_id=101,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        chat_username="ops_chat",
        raw_update_json={"update_id": 101},
    )

    result = await TelegramOpsService(db_session).scan(source="test")
    await db_session.commit()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert result == {"facts_created": 1, "recommendations_created": 1}
    assert recommendations[0].recommendation_type == "update_destination_metadata"
    assert recommendations[0].destination_id == destination.id
    assert recommendations[0].diff_json["changed"] == {
        "title": {"before": "Old Chat", "after": "Ops Chat"},
        "username": {"before": "old_chat", "after": "ops_chat"},
    }


@pytest.mark.asyncio
async def test_ops_scan_does_not_match_forum_topic_to_base_chat_destination(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="supergroup",
        chat_id="-1001",
        title="Base Chat",
        is_active=True,
    )
    await DiagnosticUpdateRepository(db_session).create(
        update_id=106,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Topic Chat",
        message_thread_id=77,
        raw_update_json={"update_id": 106},
    )

    result = await TelegramOpsService(db_session).scan(source="test")
    await db_session.commit()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert result == {"facts_created": 1, "recommendations_created": 1}
    assert recommendations[0].recommendation_type == "create_destination_from_seen_chat"
    assert recommendations[0].destination_id is None
    assert recommendations[0].action_payload_json["message_thread_id"] == 77


@pytest.mark.asyncio
async def test_ops_scan_does_not_match_base_chat_to_forum_topic_destination(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="forum_topic",
        chat_id="-1001",
        message_thread_id=77,
        title="Topic Chat",
        is_active=True,
    )
    await DiagnosticUpdateRepository(db_session).create(
        update_id=107,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Base Chat",
        raw_update_json={"update_id": 107},
    )

    result = await TelegramOpsService(db_session).scan(source="test")
    await db_session.commit()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert result == {"facts_created": 1, "recommendations_created": 1}
    assert recommendations[0].recommendation_type == "create_destination_from_seen_chat"
    assert recommendations[0].destination_id is None
    assert recommendations[0].action_payload_json["message_thread_id"] is None


@pytest.mark.asyncio
async def test_ops_preview_and_apply_create_destination(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=102,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        chat_username="ops_chat",
        message_thread_id=77,
        raw_update_json={"update_id": 102},
    )
    service = TelegramOpsService(db_session)
    await service.scan(source="test")
    recommendation = (await OpsRecommendationRepository(db_session).list(status="open"))[0]

    preview = await service.preview_action(recommendation.id, source="test", actor="tester")
    applied = await service.apply_action(recommendation.id, source="test", actor="tester")
    await db_session.commit()
    loaded = await OpsRecommendationRepository(db_session).get(recommendation.id)
    runs = await OpsActionRunRepository(db_session).list()
    destination = await DestinationRepository(db_session).get(applied["destination_id"])

    assert preview["recommendation_id"] == recommendation.id
    assert preview["diff"]["operation"] == "create"
    assert preview["run_id"] is not None
    assert applied == {
        "recommendation_id": recommendation.id,
        "status": "applied",
        "destination_id": destination.id,
        "run_id": runs[0].id,
    }
    assert loaded is not None
    assert loaded.status == "applied"
    assert destination is not None
    assert destination.bot_id == bot.id
    assert destination.kind == "forum_topic"
    assert destination.message_thread_id == 77
    assert [run.action_type for run in runs] == ["apply", "preview"]


@pytest.mark.asyncio
async def test_ops_apply_rejects_invalid_status_and_auto_apply_type(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    recommendations = OpsRecommendationRepository(db_session)
    dismissed = await recommendations.create(
        recommendation_type="create_destination_from_seen_chat",
        status="dismissed",
        risk="low",
        bot_id=bot.id,
        title="Dismissed",
        reason="Already dismissed.",
        diff_json={},
        action_payload_json={"bot_id": bot.id, "chat_id": "-1001"},
    )
    unsafe = await recommendations.create(
        recommendation_type="manual_review_only",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Manual",
        reason="Manual only.",
        diff_json={},
        action_payload_json={"bot_id": bot.id, "chat_id": "-1002"},
    )
    service = TelegramOpsService(db_session)

    with pytest.raises(TelegramOpsError, match="cannot be applied"):
        await service.apply_action(dismissed.id, source="test", actor="tester")
    with pytest.raises(TelegramOpsError, match="not allowlisted"):
        await service.apply_action(unsafe.id, source="test", actor="tester", auto_apply=True)


@pytest.mark.asyncio
async def test_ops_auto_apply_rejects_allowlisted_high_risk_recommendation(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    recommendation = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="high",
        bot_id=bot.id,
        title="High risk create",
        reason="High risk actions require manual apply.",
        diff_json={},
        action_payload_json={
            "bot_id": bot.id,
            "chat_id": "-1001",
            "message_thread_id": None,
            "kind": "supergroup",
            "title": "Ops Chat",
            "username": None,
            "is_active": True,
        },
    )

    with pytest.raises(TelegramOpsError, match="low-risk"):
        await TelegramOpsService(db_session).apply_action(
            recommendation.id,
            source="test",
            actor="tester",
            auto_apply=True,
        )
    await db_session.commit()

    assert await DestinationRepository(db_session).list() == []
    assert await OpsActionRunRepository(db_session).list() == []
    loaded = await OpsRecommendationRepository(db_session).get(recommendation.id)
    assert loaded is not None
    assert loaded.status == "open"


@pytest.mark.asyncio
async def test_ops_apply_records_failed_run_after_apply_starts(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    recommendation = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Malformed create",
        reason="Missing chat_id.",
        diff_json={},
        action_payload_json={
            "bot_id": bot.id,
            "kind": "supergroup",
            "is_active": True,
        },
    )
    recommendation_id = recommendation.id
    await db_session.commit()

    with pytest.raises(TelegramOpsError, match="missing chat_id"):
        await TelegramOpsService(db_session).apply_action(
            recommendation.id,
            source="test",
            actor="tester",
        )
    await db_session.rollback()
    runs = await OpsActionRunRepository(db_session).list()
    loaded = await OpsRecommendationRepository(db_session).get(recommendation_id)

    assert len(runs) == 1
    assert runs[0].action_type == "apply"
    assert runs[0].status == "failed"
    assert runs[0].error_message == "action payload missing chat_id"
    assert loaded is not None
    assert loaded.status == "open"


@pytest.mark.asyncio
async def test_ops_apply_records_failed_run_for_unexpected_mutation_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    recommendation = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Create",
        reason="Seen chat.",
        diff_json={},
        action_payload_json={
            "bot_id": bot.id,
            "chat_id": "-1001",
            "message_thread_id": None,
            "kind": "supergroup",
            "title": "Ops Chat",
            "username": None,
            "is_active": True,
        },
    )
    recommendation_id = recommendation.id
    await db_session.commit()

    async def fail_destination_apply(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(TelegramOpsService, "_apply_destination_action", fail_destination_apply)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await TelegramOpsService(db_session).apply_action(
            recommendation.id,
            source="test",
            actor="tester",
        )
    await db_session.rollback()
    runs = await OpsActionRunRepository(db_session).list()
    loaded = await OpsRecommendationRepository(db_session).get(recommendation_id)

    assert len(runs) == 1
    assert runs[0].action_type == "apply"
    assert runs[0].status == "failed"
    assert runs[0].error_message == "database unavailable"
    assert loaded is not None
    assert loaded.status == "open"


@pytest.mark.asyncio
async def test_ops_apply_records_failed_run_for_flush_failure_inside_savepoint(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    recommendation = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Create",
        reason="Seen chat.",
        diff_json={},
        action_payload_json={
            "bot_id": bot.id,
            "chat_id": "-1001",
            "message_thread_id": None,
            "kind": "supergroup",
            "title": "Ops Chat",
            "username": None,
            "is_active": True,
        },
    )
    recommendation_id = recommendation.id
    await db_session.commit()

    async def fail_with_flush_error(
        self: DestinationRepository,
        bot_id: int,
        chat_id: str,
        message_thread_id: int | None = None,
        **_values: object,
    ) -> Destination:
        del bot_id, chat_id, message_thread_id
        self.session.add(
            Destination(
                bot_id=bot.id,
                kind="supergroup",
                chat_id=None,  # type: ignore[arg-type]
            )
        )
        await self.session.flush()
        raise AssertionError("flush should fail before this line")

    monkeypatch.setattr(DestinationRepository, "upsert_by_chat", fail_with_flush_error)

    with pytest.raises(IntegrityError):
        await TelegramOpsService(db_session).apply_action(
            recommendation.id,
            source="test",
            actor="tester",
        )
    await db_session.rollback()

    bind = db_session.bind
    assert bind is not None
    fresh_session_factory = async_sessionmaker(bind, expire_on_commit=False)
    async with fresh_session_factory() as fresh_session:
        runs = await OpsActionRunRepository(fresh_session).list()
        loaded = await OpsRecommendationRepository(fresh_session).get(recommendation_id)

    assert len(runs) == 1
    assert runs[0].action_type == "apply"
    assert runs[0].status == "failed"
    assert "NOT NULL constraint failed" in (runs[0].error_message or "")
    assert loaded is not None
    assert loaded.status == "open"


@pytest.mark.asyncio
async def test_ops_apply_durable_failed_run_survives_file_sqlite_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ops.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            bot = await BotRepository(session).create(name="ops", token="123:abc")
            recommendation = await OpsRecommendationRepository(session).create(
                recommendation_type="create_destination_from_seen_chat",
                status="open",
                risk="low",
                bot_id=bot.id,
                title="Create",
                reason="Seen chat.",
                diff_json={},
                action_payload_json={
                    "bot_id": bot.id,
                    "chat_id": "-1001",
                    "message_thread_id": None,
                    "kind": "supergroup",
                    "title": "Ops Chat",
                    "username": None,
                    "is_active": True,
                },
            )
            recommendation_id = recommendation.id
            await session.commit()

            async def fail_with_flush_error(
                self: DestinationRepository,
                bot_id: int,
                chat_id: str,
                message_thread_id: int | None = None,
                **_values: object,
            ) -> Destination:
                del bot_id, chat_id, message_thread_id
                self.session.add(
                    Destination(
                        bot_id=bot.id,
                        kind="supergroup",
                        chat_id=None,  # type: ignore[arg-type]
                    )
                )
                await self.session.flush()
                raise AssertionError("flush should fail before this line")

            monkeypatch.setattr(DestinationRepository, "upsert_by_chat", fail_with_flush_error)

            with pytest.raises(IntegrityError):
                await TelegramOpsService(session).apply_action(
                    recommendation_id,
                    source="test",
                    actor="tester",
                )
            await session.rollback()

        async with session_factory() as fresh_session:
            runs = await OpsActionRunRepository(fresh_session).list()
            loaded = await OpsRecommendationRepository(fresh_session).get(recommendation_id)

        assert len(runs) == 1
        assert runs[0].action_type == "apply"
        assert runs[0].status == "failed"
        assert "NOT NULL constraint failed" in (runs[0].error_message or "")
        assert loaded is not None
        assert loaded.status == "open"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ops_scan_does_not_duplicate_open_or_previewed_recommendations(
    db_session: AsyncSession,
) -> None:
    await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=103,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        raw_update_json={"update_id": 103},
    )
    service = TelegramOpsService(db_session)

    first = await service.scan(source="test")
    recommendation = (await OpsRecommendationRepository(db_session).list(status="open"))[0]
    await service.preview_action(recommendation.id, source="test", actor="tester")
    second = await service.scan(source="test")
    await db_session.commit()
    recommendations = await OpsRecommendationRepository(db_session).list()

    assert first == {"facts_created": 1, "recommendations_created": 1}
    assert second == {"facts_created": 1, "recommendations_created": 0}
    assert len(recommendations) == 1
    assert recommendations[0].status == "previewed"


@pytest.mark.asyncio
async def test_ops_scan_duplicate_suppression_ignores_mutable_title_changes(
    db_session: AsyncSession,
) -> None:
    await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=108,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Old Title",
        message_thread_id=77,
        raw_update_json={"update_id": 108},
    )
    service = TelegramOpsService(db_session)
    first = await service.scan(source="test")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=109,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="New Title",
        message_thread_id=77,
        raw_update_json={"update_id": 109},
    )

    second = await service.scan(source="test")
    await db_session.commit()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert first == {"facts_created": 1, "recommendations_created": 1}
    assert second == {"facts_created": 2, "recommendations_created": 0}
    assert len(recommendations) == 1
    assert recommendations[0].action_payload_json["title"] == "New Title"
    assert recommendations[0].diff_json["after"]["title"] == "New Title"


@pytest.mark.asyncio
async def test_ops_scan_with_no_active_bot_creates_fact_without_recommendation(
    db_session: AsyncSession,
) -> None:
    await BotRepository(db_session).create(name="inactive", token="123:abc", is_active=False)
    await DiagnosticUpdateRepository(db_session).create(
        update_id=104,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        raw_update_json={"update_id": 104},
    )

    result = await TelegramOpsService(db_session).scan(source="test")
    await db_session.commit()
    facts = await OpsFactRepository(db_session).list()
    recommendations = await OpsRecommendationRepository(db_session).list()

    assert result == {"facts_created": 1, "recommendations_created": 0}
    assert facts[0].chat_id == "-1001"
    assert recommendations == []


@pytest.mark.asyncio
async def test_ops_rule_updates_pause_resume_and_run(
    db_session: AsyncSession,
) -> None:
    await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=105,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        raw_update_json={"update_id": 105},
    )
    service = TelegramOpsService(db_session)
    await service.scan(source="test")
    rule = next(
        item
        for item in await service.list_rules()
        if item.rule_key == "create_destination_from_seen_chat"
    )

    updated = await service.update_rule(rule.id, mode="auto_apply", risk_limit="low")
    await service.scan(source="test")
    preserved = await OpsAutomationRuleRepository(db_session).get(rule.id)
    paused = await service.pause_rule(rule.id)
    paused_state = paused.is_paused
    resumed = await service.resume_rule(rule.id)
    run_result = await service.run_rule(rule.id, source="test", actor="tester")
    await db_session.commit()
    destination = (await DestinationRepository(db_session).list())[0]
    runs = await OpsActionRunRepository(db_session).list()

    assert updated.mode == "auto_apply"
    assert preserved is not None
    assert preserved.mode == "auto_apply"
    assert paused_state is True
    assert resumed.is_paused is False
    assert run_result["rule_id"] == rule.id
    assert run_result["applied"] == 1
    assert run_result["skipped"] == 0
    assert run_result["failed"] == 0
    assert destination.chat_id == "-1001"
    assert [run.action_type for run in runs] == [
        "run_rule",
        "apply",
        "resume_rule",
        "pause_rule",
        "update_rule",
    ]
    assert runs[0].result_json == {
        "rule_id": rule.id,
        "applied": 1,
        "skipped": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_ops_update_rule_rejects_auto_apply_with_non_low_risk_limit(
    db_session: AsyncSession,
) -> None:
    service = TelegramOpsService(db_session)
    rule = next(
        item
        for item in await service.list_rules()
        if item.rule_key == "create_destination_from_seen_chat"
    )

    with pytest.raises(TelegramOpsError, match="low risk_limit"):
        await service.update_rule(rule.id, mode="auto_apply", risk_limit="medium")

    await service.update_rule(rule.id, mode="auto_apply", risk_limit="low")
    with pytest.raises(TelegramOpsError, match="low risk_limit"):
        await service.update_rule(rule.id, risk_limit="high")


@pytest.mark.asyncio
async def test_ops_run_rule_counts_unexpected_apply_exceptions(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind = db_session.bind
    assert bind is not None
    session_factory = async_sessionmaker(bind, expire_on_commit=False)
    await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=110,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        raw_update_json={"update_id": 110},
    )
    service = TelegramOpsService(db_session, action_log_session_factory=session_factory)
    await service.scan(source="test")
    rule = next(
        item
        for item in await service.list_rules()
        if item.rule_key == "create_destination_from_seen_chat"
    )
    await service.update_rule(rule.id, mode="auto_apply", risk_limit="low")
    await db_session.commit()

    async def fail_destination_apply(*_args: object, **_kwargs: object) -> Destination:
        raise RuntimeError("apply exploded")

    monkeypatch.setattr(
        TelegramOpsService,
        "_apply_destination_action",
        fail_destination_apply,
    )

    result = await service.run_rule(rule.id, source="test", actor="tester")
    await db_session.commit()
    runs = await OpsActionRunRepository(db_session).list()
    summary_run = next(run for run in runs if run.action_type == "run_rule")
    failed_apply_run = next(run for run in runs if run.action_type == "apply")

    assert result == {"rule_id": rule.id, "applied": 0, "skipped": 0, "failed": 1}
    assert summary_run.status == "failed"
    assert summary_run.result_json == result
    assert failed_apply_run.status == "failed"
    assert failed_apply_run.error_message == "apply exploded"


@pytest.mark.asyncio
async def test_ops_run_rule_isolates_apply_transactions_after_failure(
    db_session: AsyncSession,
) -> None:
    bind = db_session.bind
    assert bind is not None
    session_factory = async_sessionmaker(bind, expire_on_commit=False)
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    rule = await OpsAutomationRuleRepository(db_session).upsert_by_key(
        "create_destination_from_seen_chat",
        title="Create destinations from observed chats",
        mode="auto_apply",
        is_enabled=True,
        is_paused=False,
        risk_limit="low",
        config_json={},
    )
    invalid = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Malformed create",
        reason="Missing chat_id.",
        diff_json={},
        action_payload_json={
            "bot_id": bot.id,
            "kind": "supergroup",
            "is_active": True,
        },
    )
    valid = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Valid create",
        reason="Seen chat.",
        diff_json={
            "operation": "create",
            "after": {"bot_id": bot.id, "chat_id": "-1001"},
        },
        action_payload_json={
            "bot_id": bot.id,
            "chat_id": "-1001",
            "message_thread_id": None,
            "kind": "supergroup",
            "title": "Ops Chat",
            "username": None,
            "is_active": True,
        },
    )
    await db_session.commit()

    result = await TelegramOpsService(
        db_session,
        action_log_session_factory=session_factory,
    ).run_rule(rule.id, source="test", actor="tester")
    await db_session.commit()

    async with session_factory() as fresh_session:
        destinations = await DestinationRepository(fresh_session).list()
        loaded_valid = await OpsRecommendationRepository(fresh_session).get(valid.id)
        loaded_invalid = await OpsRecommendationRepository(fresh_session).get(invalid.id)
        loaded_rule = await OpsAutomationRuleRepository(fresh_session).get(rule.id)
        runs = await OpsActionRunRepository(fresh_session).list()

    apply_runs_by_recommendation = {
        run.recommendation_id: run
        for run in runs
        if run.action_type == "apply"
    }
    summary_runs = [run for run in runs if run.action_type == "run_rule"]

    assert result == {"rule_id": rule.id, "applied": 1, "skipped": 0, "failed": 1}
    assert len(destinations) == 1
    assert destinations[0].chat_id == "-1001"
    assert loaded_valid is not None
    assert loaded_valid.status == "applied"
    assert loaded_valid.destination_id == destinations[0].id
    assert loaded_invalid is not None
    assert loaded_invalid.status == "open"
    assert apply_runs_by_recommendation[valid.id].status == "succeeded"
    assert apply_runs_by_recommendation[invalid.id].status == "failed"
    assert apply_runs_by_recommendation[invalid.id].error_message == (
        "action payload missing chat_id"
    )
    assert loaded_rule is not None
    assert loaded_rule.last_result == "applied=1 skipped=0 failed=1"
    assert len(summary_runs) == 1
    assert summary_runs[0].status == "failed"
    assert summary_runs[0].result_json == result


@pytest.mark.asyncio
async def test_ops_run_rule_records_skip_summary_run(
    db_session: AsyncSession,
) -> None:
    service = TelegramOpsService(db_session)
    rule = next(
        item
        for item in await service.list_rules()
        if item.rule_key == "create_destination_from_seen_chat"
    )

    result = await service.run_rule(rule.id, source="test", actor="tester")
    await db_session.commit()
    runs = await OpsActionRunRepository(db_session).list()

    assert result == {"rule_id": rule.id, "applied": 0, "skipped": 1, "failed": 0}
    assert len(runs) == 1
    assert runs[0].action_type == "run_rule"
    assert runs[0].status == "succeeded"
    assert runs[0].result_json == result


@pytest.mark.asyncio
async def test_ops_dismiss_recommendation_marks_dismissed(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    recommendation = await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        title="Create",
        reason="Seen chat.",
        diff_json={},
        action_payload_json={"bot_id": bot.id, "chat_id": "-1001"},
    )

    result = await TelegramOpsService(db_session).dismiss_recommendation(recommendation.id)
    await db_session.commit()
    loaded = await OpsRecommendationRepository(db_session).get(recommendation.id)
    runs = await OpsActionRunRepository(db_session).list()

    assert result == {"recommendation_id": recommendation.id, "status": "dismissed"}
    assert loaded is not None
    assert loaded.status == "dismissed"
    assert len(runs) == 1
    assert runs[0].action_type == "dismiss"
    assert runs[0].recommendation_id == recommendation.id
    assert runs[0].status == "succeeded"


def test_mcp_coverage_matrix_reports_rows_and_missing_required_tools() -> None:
    coverage = McpCoverageService(
        {
            "list_bots",
            "list_destinations",
            "list_message_templates",
            "send_text",
            "dry_run_send",
        }
    ).matrix()
    read_model = McpCoverageRead.model_validate(coverage)

    domains = {row["domain"] for row in coverage["rows"]}

    assert domains == {
        "health",
        "bots",
        "destinations",
        "templates",
        "send",
        "send_profiles",
        "send_batches",
        "media",
        "history",
        "reliability",
        "diagnostics",
        "discovery",
        "analytics",
        "mtproto",
        "operations_backup",
        "audit",
        "mcp_settings",
        "telegram_ops",
    }
    assert "run_ops_scan" not in coverage["missing_catalog_tools"]
    assert "update_mcp_settings" in coverage["missing_catalog_tools"]
    assert "check_destination" in coverage["missing_enabled_tools"]
    assert "list_bots" not in coverage["missing_enabled_tools"]
    assert "run_ops_scan" in coverage["missing_enabled_tools"]
    assert read_model.missing_enabled_tools == coverage["missing_enabled_tools"]
    assert read_model.missing_catalog_tools == coverage["missing_catalog_tools"]
    assert set(McpCoverageRead.model_fields) == {
        "rows",
        "missing_enabled_tools",
        "missing_catalog_tools",
    }
