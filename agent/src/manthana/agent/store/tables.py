"""SQLModel table definitions for the local store.

Design: each table carries **typed index columns** (used for ``WHERE`` / ``ORDER
BY``) plus an authoritative ``data`` JSON column holding the full Pydantic model
dump. Domain objects are always reconstructed from ``data`` (so no field ever
drifts between the contract and the table), while the index columns keep queries
fast. This is the document-store-with-indexes pattern re-expressed from
affaan-m/ECC ``scripts/lib/state-store/`` (MIT, 2026 Affaan Mustafa), whose store
keeps schema-validated JSON documents; here the validation lives in
``manthana.schemas`` and the backend is SQLite via SQLModel instead of a JSON
file.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class SessionRow(SQLModel, table=True):
    """Persisted ``manthana.schemas.Session`` (index columns + data)."""

    __tablename__ = "session"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    actor: str = Field(index=True)
    surface: str = Field(index=True)
    project: str = Field(index=True)
    mode: str = Field(index=True)
    started_at: str = Field(index=True)  # ISO-8601 (lexically sortable)
    ended_at: str | None = Field(default=None)
    resumed_from: str | None = Field(default=None, index=True)
    turn_count: int = Field(default=0)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class TurnRow(SQLModel, table=True):
    """Persisted ``manthana.schemas.Turn`` (index columns + data)."""

    __tablename__ = "turn"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    actor: str = Field(index=True)
    seq: int = Field(index=True)
    role: str = Field(index=True)
    timestamp: str | None = Field(default=None)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class CompactionRow(SQLModel, table=True):
    """Persisted compaction (Base or Engineering; index columns + data)."""

    __tablename__ = "compaction"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    actor: str = Field(index=True)
    project: str = Field(index=True)
    surface: str = Field(index=True)
    kind: str = Field(index=True)
    outcome: str = Field(index=True)
    released: bool = Field(default=False, index=True)
    started_at: str = Field(index=True)
    tier_used: str | None = Field(default=None)
    est_cost_usd: float | None = Field(default=None)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ActionAuditRow(SQLModel, table=True):
    """Persisted ``manthana.schemas.ActionAuditEntry`` — the action audit log."""

    __tablename__ = "action_audit"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    action_id: str = Field(index=True)
    actor: str | None = Field(default=None, index=True)
    fired_at: str = Field(index=True)
    outcome: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ConsentRow(SQLModel, table=True):
    """Persisted ``manthana.schemas.ConsentEntry`` — the consent registry."""

    __tablename__ = "consent"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    subject: str = Field(index=True)
    action_category: str = Field(index=True)
    state: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class SyncStateRow(SQLModel, table=True):
    """Tracks which compactions (and their raw transcripts) have synced to the
    org server. Metadata and raw are tracked separately so a failed raw upload
    retries without re-pushing metadata."""

    __tablename__ = "sync_state"  # type: ignore[assignment]

    compaction_id: str = Field(primary_key=True)
    synced_at: str | None = Field(default=None)
    raw_synced_at: str | None = Field(default=None)


__all__ = [
    "SessionRow",
    "TurnRow",
    "CompactionRow",
    "ActionAuditRow",
    "ConsentRow",
    "SyncStateRow",
]
