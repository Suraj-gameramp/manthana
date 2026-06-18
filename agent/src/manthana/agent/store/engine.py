"""SQLite engine creation + per-connection configuration.

Sets the same pragmas ECC used (``foreign_keys=ON``, WAL journaling) and, if the
optional ``sqlite-vec`` extension is installed, loads it so vector features can be
added later without a schema change. ``sqlite-vec`` is wired but optional: a
missing package or a Python build without ``enable_load_extension`` is ignored.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

MEMORY = ":memory:"


def _configure_connection(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001 - WAL is rejected for in-memory/readonly
        pass
    cursor.close()
    _try_load_sqlite_vec(dbapi_conn)


def _try_load_sqlite_vec(dbapi_conn: Any) -> None:
    """Best-effort load of the optional sqlite-vec extension."""
    try:
        import sqlite_vec  # type: ignore[import-not-found]

        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)
    except Exception:  # noqa: BLE001 - optional; absence is expected
        pass


def create_db_engine(db_path: str | Path) -> Engine:
    """Create a configured SQLite engine for ``db_path`` (or ``:memory:``)."""
    path_str = str(db_path)
    if path_str == MEMORY:
        # StaticPool keeps a single in-memory connection alive across the
        # session (otherwise each checkout gets a fresh, empty database).
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(f"sqlite:///{Path(path_str).resolve()}")
    event.listen(engine, "connect", _configure_connection)
    return engine


__all__ = ["create_db_engine", "MEMORY"]
