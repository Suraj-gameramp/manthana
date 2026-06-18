"""Versioned schema migrations for the local SQLite store.

Re-expressed in Python from affaan-m/ECC ``scripts/lib/state-store/migrations.js``
(MIT, 2026 Affaan Mustafa): a ``schema_migrations`` table tracks applied
versions; pending migrations apply in ascending order inside a single
transaction; application is idempotent. ECC's migrations were raw SQL strings;
migration 1 here builds the tables from the SQLModel metadata, and later
migrations may be raw SQL (for ALTERs) or callables.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import SQLModel

# Importing the tables registers them on SQLModel.metadata so migration 1 can
# create them.
from . import tables  # noqa: F401


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def _create_initial_tables(conn: Connection) -> None:
    """v1 core tables: session, turn, compaction."""
    SQLModel.metadata.create_all(
        conn,
        tables=[
            tables.SessionRow.__table__,  # type: ignore[list-item]
            tables.TurnRow.__table__,  # type: ignore[list-item]
            tables.CompactionRow.__table__,  # type: ignore[list-item]
        ],
    )


def _create_action_consent_tables(conn: Connection) -> None:
    """Action audit log + consent registry (added in v2)."""
    SQLModel.metadata.create_all(
        conn,
        tables=[
            tables.ActionAuditRow.__table__,  # type: ignore[list-item]
            tables.ConsentRow.__table__,  # type: ignore[list-item]
        ],
    )


def _create_sync_state_table(conn: Connection) -> None:
    """Sync-state tracking for agent→server sync (added in v3)."""
    SQLModel.metadata.create_all(conn, tables=[tables.SyncStateRow.__table__])  # type: ignore[list-item]


# Each migration creates exactly the tables it introduces (create_all is
# idempotent / checkfirst), so a database at an older version gains the new
# tables when later migrations apply, and fresh databases get everything in order.
MIGRATIONS: list[Migration] = [
    Migration(version=1, name="001_initial", apply=_create_initial_tables),
    Migration(version=2, name="002_action_consent_tables", apply=_create_action_consent_tables),
    Migration(version=3, name="003_sync_state", apply=_create_sync_state_table),
]

_SCHEMA_MIGRATIONS_DDL = text(
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "  version INTEGER PRIMARY KEY,"
    "  name TEXT NOT NULL,"
    "  applied_at TEXT NOT NULL"
    ")"
)


def applied_versions(conn: Connection) -> set[int]:
    conn.execute(_SCHEMA_MIGRATIONS_DDL)
    rows = conn.execute(text("SELECT version FROM schema_migrations"))
    return {row[0] for row in rows}


def run_migrations(engine: Engine) -> list[int]:
    """Apply all pending migrations in order; return the full applied version list."""
    with engine.begin() as conn:
        done = applied_versions(conn)
        for migration in MIGRATIONS:
            if migration.version in done:
                continue
            migration.apply(conn)
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, name, applied_at) "
                    "VALUES (:version, :name, :applied_at)"
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(UTC).isoformat(),
                },
            )
        final = applied_versions(conn)
    return sorted(final)


__all__ = ["Migration", "MIGRATIONS", "run_migrations", "applied_versions"]
