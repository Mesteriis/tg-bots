import json
import sqlite3

import pytest

from tg_bot_aggregator.migration_repair import (
    DRIFT_VERSION,
    HEAD_VERSION,
    REQUIRED_METADATA_CREATED_TABLES,
    repair_sqlite_metadata_created_schema,
)


def _create_table(connection: sqlite3.Connection, table_name: str) -> None:
    connection.execute(f'create table "{table_name}" (id integer primary key)')


def _create_repairable_database(path: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("create table alembic_version (version_num varchar(32) primary key)")
        connection.execute("insert into alembic_version values (?)", (DRIFT_VERSION,))
        connection.execute("create table api_tokens (id integer primary key, scopes_json json)")
        connection.execute(
            "insert into api_tokens (id, scopes_json) values (1, ?)",
            (json.dumps(["read", "mcp_admin"]),),
        )
        connection.execute(
            """
            create table destinations (
                id integer primary key,
                bot_id integer,
                chat_id varchar(200),
                message_thread_id integer
            )
            """
        )
        connection.execute(
            """
            create table runtime_settings (
                id integer primary key,
                reliability_enabled boolean,
                send_default_mode varchar(40),
                send_global_rate_per_minute integer,
                send_bot_rate_per_minute integer,
                send_chat_rate_per_minute integer,
                send_destination_rate_per_minute integer,
                send_retry_base_delay_seconds float,
                send_retry_max_delay_seconds float,
                send_worker_lease_seconds integer,
                send_stale_lock_grace_seconds integer,
                send_dedupe_window_seconds integer
            )
            """
        )
        connection.execute(
            """
            create table send_history (
                id integer primary key,
                status varchar(40),
                next_retry_at datetime,
                priority integer,
                locked_at datetime,
                locked_by varchar(200),
                lock_expires_at datetime,
                last_attempt_at datetime,
                retry_after_seconds integer,
                last_error_kind varchar(80),
                dedupe_window_key varchar(200)
            )
            """
        )
        connection.execute(
            """
            create table send_attempts (
                id integer primary key,
                send_history_id integer
            )
            """
        )
        connection.execute(
            "create table ops_facts (id integer primary key, fact_type varchar(80))"
        )
        connection.execute(
            "create table ops_recommendations (id integer primary key, status varchar(40))"
        )
        for table_name in REQUIRED_METADATA_CREATED_TABLES - {
            "runtime_settings",
            "send_attempts",
            "ops_facts",
            "ops_recommendations",
        }:
            _create_table(connection, table_name)


def test_repair_sqlite_metadata_created_schema_stamps_head_and_indexes(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    _create_repairable_database(str(db_path))

    repaired = repair_sqlite_metadata_created_schema(f"sqlite:///{db_path}")

    assert repaired is True
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone() == (
            HEAD_VERSION,
        )
        indexes = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'index'"
            )
        }
        assert "ix_send_history_due_priority" in indexes
        assert "ix_send_history_lock_expires" in indexes
        assert "ix_send_attempts_send_history_id" in indexes
        assert "ix_ops_facts_fact_type" in indexes
        assert "ix_ops_recommendations_status" in indexes
        assert "uq_destinations_bot_chat_thread" in indexes
        scopes_json = connection.execute(
            "select scopes_json from api_tokens where id = 1"
        ).fetchone()[0]
        assert json.loads(scopes_json) == ["read", "mcp_admin", "ops_admin"]


def test_repair_sqlite_metadata_created_schema_skips_current_database(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("create table alembic_version (version_num varchar(32) primary key)")
        connection.execute("insert into alembic_version values (?)", (HEAD_VERSION,))

    assert repair_sqlite_metadata_created_schema(f"sqlite:///{db_path}") is False


def test_repair_sqlite_metadata_created_schema_refuses_unknown_partial_schema(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("create table alembic_version (version_num varchar(32) primary key)")
        connection.execute("insert into alembic_version values (?)", (DRIFT_VERSION,))

    with pytest.raises(RuntimeError, match="missing tables"):
        repair_sqlite_metadata_created_schema(f"sqlite:///{db_path}")
