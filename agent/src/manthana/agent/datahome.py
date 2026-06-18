"""Resolve ``MANTHANA_DATA_HOME`` — the root of the employee-owned local store.

Re-expressed in Python from the data-home resolution pattern in
affaan-m/ECC ``scripts/lib/agent-data-home.js`` (MIT, 2026 Affaan Mustafa):
the ``ECC_AGENT_DATA_HOME`` environment override is renamed to
``MANTHANA_DATA_HOME``, tilde/relative expansion is preserved, and the
Cursor-specific config branches are dropped for v1. The local SQLite database
lives at ``$MANTHANA_DATA_HOME/manthana.db`` (decisions doc: Storage).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_HOME_ENV = "MANTHANA_DATA_HOME"
DEFAULT_DIR_NAME = ".manthana"
DB_FILENAME = "manthana.db"


def _expand(value: str | None, base: Path | None = None) -> Path | None:
    """Expand ~ and resolve relative paths; return None for empty input."""
    if not value or not value.strip():
        return None
    trimmed = value.strip()
    if trimmed.startswith("~"):
        return Path(trimmed).expanduser()
    candidate = Path(trimmed)
    if candidate.is_absolute():
        return candidate
    return (base or Path.cwd()) / candidate


def resolve_data_home() -> Path:
    """Resolve the data home without mutating the environment.

    Order: ``$MANTHANA_DATA_HOME`` (expanded) → ``~/.manthana``.
    """
    from_env = _expand(os.environ.get(DATA_HOME_ENV))
    if from_env is not None:
        return from_env
    return Path.home() / DEFAULT_DIR_NAME


def ensure_data_home() -> Path:
    """Resolve the data home and create it if missing."""
    path = resolve_data_home()
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    """Path to the local SQLite database file."""
    return resolve_data_home() / DB_FILENAME


__all__ = [
    "DATA_HOME_ENV",
    "DEFAULT_DIR_NAME",
    "DB_FILENAME",
    "resolve_data_home",
    "ensure_data_home",
    "db_path",
]
