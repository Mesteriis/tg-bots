from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tg_bot_aggregator.core.config import get_settings

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

ADD_COLUMN_SQL: dict[str, dict[str, str]] = {
    "runtime_settings": {
        "reliability_enabled": (
            "alter table runtime_settings add column reliability_enabled boolean"
        ),
        "send_default_mode": (
            "alter table runtime_settings add column send_default_mode varchar(40)"
        ),
        "send_global_rate_per_minute": (
            "alter table runtime_settings add column send_global_rate_per_minute integer"
        ),
        "send_bot_rate_per_minute": (
            "alter table runtime_settings add column send_bot_rate_per_minute integer"
        ),
        "send_chat_rate_per_minute": (
            "alter table runtime_settings add column send_chat_rate_per_minute integer"
        ),
        "send_destination_rate_per_minute": (
            "alter table runtime_settings add column send_destination_rate_per_minute integer"
        ),
        "send_retry_base_delay_seconds": (
            "alter table runtime_settings add column send_retry_base_delay_seconds float"
        ),
        "send_retry_max_delay_seconds": (
            "alter table runtime_settings add column send_retry_max_delay_seconds float"
        ),
        "send_worker_lease_seconds": (
            "alter table runtime_settings add column send_worker_lease_seconds integer"
        ),
        "send_stale_lock_grace_seconds": (
            "alter table runtime_settings add column send_stale_lock_grace_seconds integer"
        ),
        "send_dedupe_window_seconds": (
            "alter table runtime_settings add column send_dedupe_window_seconds integer"
        ),
    },
    "send_history": {
        "priority": "alter table send_history add column priority integer not null default 100",
        "locked_at": "alter table send_history add column locked_at datetime",
        "locked_by": "alter table send_history add column locked_by varchar(200)",
        "lock_expires_at": "alter table send_history add column lock_expires_at datetime",
        "last_attempt_at": "alter table send_history add column last_attempt_at datetime",
        "retry_after_seconds": "alter table send_history add column retry_after_seconds integer",
        "last_error_kind": "alter table send_history add column last_error_kind varchar(80)",
        "dedupe_window_key": "alter table send_history add column dedupe_window_key varchar(200)",
    },
}

INDEX_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "destinations": {"bot_id", "chat_id", "message_thread_id"},
    "send_history": {"id", "status", "next_retry_at", "priority", "lock_expires_at"},
    "send_attempts": {"send_history_id"},
    "ops_facts": {"fact_type"},
    "ops_recommendations": {"status"},
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


def _validate_metadata_created_tables(connection: sqlite3.Connection) -> None:
    tables = _table_names(connection)
    missing_tables = sorted(REQUIRED_METADATA_CREATED_TABLES - tables)
    if missing_tables:
        joined = ", ".join(missing_tables)
        raise RuntimeError(
            "Cannot repair Alembic metadata-created schema drift; missing tables: "
            f"{joined}"
        )


def _validate_index_columns(connection: sqlite3.Connection) -> None:
    missing_columns: dict[str, list[str]] = {}
    for table_name, required_columns in INDEX_REQUIRED_COLUMNS.items():
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


def _add_missing_reliability_columns(connection: sqlite3.Connection) -> None:
    for table_name, column_sql_by_name in ADD_COLUMN_SQL.items():
        existing_columns = _column_names(connection, table_name)
        for column_name, add_column_sql in column_sql_by_name.items():
            if column_name not in existing_columns:
                connection.execute(add_column_sql)


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

        _validate_metadata_created_tables(connection)
        _add_missing_reliability_columns(connection)
        _validate_index_columns(connection)
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
