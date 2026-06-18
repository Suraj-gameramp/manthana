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
    SQLModel.metadata.create_all(conn)


MIGRATIONS: list[Migration] = [
    Migration(version=1, name="001_initial", apply=_create_initial_tables),
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
