from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tg_bot_aggregator.config import get_settings

DRIFT_VERSION = "0004_ops_automation"
HEAD_VERSION = "0009_destination_chat_thread_identity"

REQUIRED_METADATA_CREATED_TABLES = {
    "send_profiles",
    "send_batches",
    "send_batch_items",
    "diagnostic_updates",
    "runtime_settings",
    "backup_runs",
    "runtime_advanced_settings",
    "destination_health",
    "message_template_versions",
    "send_attempts",
    "ops_facts",
    "ops_recommendations",
    "ops_automation_rules",
    "ops_action_runs",
    "mcp_coverage_snapshots",
}

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "runtime_settings": {
        "reliability_enabled",
        "send_default_mode",
        "send_global_rate_per_minute",
        "send_bot_rate_per_minute",
        "send_chat_rate_per_minute",
        "send_destination_rate_per_minute",
        "send_retry_base_delay_seconds",
        "send_retry_max_delay_seconds",
        "send_worker_lease_seconds",
        "send_stale_lock_grace_seconds",
        "send_dedupe_window_seconds",
    },
    "send_history": {
        "priority",
        "locked_at",
        "locked_by",
        "lock_expires_at",
        "last_attempt_at",
        "retry_after_seconds",
        "last_error_kind",
        "dedupe_window_key",
    },
}


def _sqlite_path_from_url(database_url: str) -> Path | None:
    prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
    for prefix in prefixes:
        if database_url.startswith(prefix):
            raw_path = database_url.removeprefix(prefix)
            if raw_path == ":memory:":
                return None
            return Path(raw_path)
    return None


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table'"
        ).fetchall()
    }


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'pragma table_info("{table_name}")')}


def _current_alembic_version(connection: sqlite3.Connection) -> str | None:
    if "alembic_version" not in _table_names(connection):
        return None
    row = connection.execute("select version_num from alembic_version").fetchone()
    if row is None:
        return None
    return str(row[0])


def _validate_metadata_created_schema(connection: sqlite3.Connection) -> None:
    tables = _table_names(connection)
    missing_tables = sorted(REQUIRED_METADATA_CREATED_TABLES - tables)
    if missing_tables:
        joined = ", ".join(missing_tables)
        raise RuntimeError(
            "Cannot repair Alembic metadata-created schema drift; missing tables: "
            f"{joined}"
        )

    missing_columns: dict[str, list[str]] = {}
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        existing_columns = _column_names(connection, table_name)
        missing = sorted(required_columns - existing_columns)
        if missing:
            missing_columns[table_name] = missing
    if missing_columns:
        details = "; ".join(
            f"{table}: {', '.join(columns)}" for table, columns in missing_columns.items()
        )
        raise RuntimeError(
            "Cannot repair Alembic metadata-created schema drift; missing columns: "
            f"{details}"
        )


def _create_missing_migration_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create index if not exists ix_send_history_due_priority
        on send_history (status, next_retry_at, priority, id)
        """
    )
    connection.execute(
        """
        create index if not exists ix_send_history_lock_expires
        on send_history (status, lock_expires_at)
        """
    )
    connection.execute(
        """
        create index if not exists ix_send_attempts_send_history_id
        on send_attempts (send_history_id)
        """
    )
    connection.execute(
        """
        create index if not exists ix_ops_facts_fact_type
        on ops_facts (fact_type)
        """
    )
    connection.execute(
        """
        create index if not exists ix_ops_recommendations_status
        on ops_recommendations (status)
        """
    )
    connection.execute(
        """
        create unique index if not exists uq_destinations_bot_chat_thread
        on destinations (bot_id, chat_id, coalesce(message_thread_id, -1))
        """
    )


def _backfill_ops_admin_scope(connection: sqlite3.Connection) -> None:
    if "api_tokens" not in _table_names(connection):
        return

    rows = connection.execute("select id, scopes_json from api_tokens").fetchall()
    for token_id, scopes_value in rows:
        if scopes_value is None:
            continue
        try:
            scopes = json.loads(scopes_value) if isinstance(scopes_value, str) else scopes_value
        except json.JSONDecodeError:
            continue
        if not isinstance(scopes, list):
            continue
        normalized = [scope for scope in scopes if isinstance(scope, str)]
        if "mcp_admin" not in normalized or "ops_admin" in normalized:
            continue
        connection.execute(
            "update api_tokens set scopes_json = ? where id = ?",
            (json.dumps([*normalized, "ops_admin"]), token_id),
        )


def repair_sqlite_metadata_created_schema(database_url: str) -> bool:
    sqlite_path = _sqlite_path_from_url(database_url)
    if sqlite_path is None or not sqlite_path.exists():
        return False

    with sqlite3.connect(sqlite_path) as connection:
        current_version = _current_alembic_version(connection)
        if current_version != DRIFT_VERSION:
            return False

        _validate_metadata_created_schema(connection)
        _create_missing_migration_indexes(connection)
        _backfill_ops_admin_scope(connection)
        connection.execute("update alembic_version set version_num = ?", (HEAD_VERSION,))
        connection.commit()
        return True


def main() -> None:
    repaired = repair_sqlite_metadata_created_schema(get_settings().database_url)
    if repaired:
        print(
            "Repaired Alembic metadata-created schema drift: "
            f"{DRIFT_VERSION} -> {HEAD_VERSION}"
        )


if __name__ == "__main__":
    main()
