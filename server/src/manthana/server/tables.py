"""Server SQLModel tables (multi-tenant: Org > Team > Actor; Project is a tag).

Distinct ``__tablename__``s (``released_compaction`` etc.) avoid any clash with
the local-agent tables on the shared SQLModel metadata. Same document-store
pattern as the local store: typed index columns + an authoritative ``data`` JSON.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class OrgRow(SQLModel, table=True):
    __tablename__ = "org"  # type: ignore[assignment]
    id: str = Field(primary_key=True)
    name: str
    created_at: str


class TeamRow(SQLModel, table=True):
    __tablename__ = "team"  # type: ignore[assignment]
    id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    name: str


class ActorRow(SQLModel, table=True):
    __tablename__ = "actor"  # type: ignore[assignment]
    id: str = Field(primary_key=True)  # org email
    org_id: str = Field(index=True)
    team_id: str = Field(index=True)
    display_name: str | None = Field(default=None)


class ReleasedCompactionRow(SQLModel, table=True):
    __tablename__ = "released_compaction"  # type: ignore[assignment]
    id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    team_id: str = Field(index=True)
    actor: str = Field(index=True)
    project: str = Field(index=True)
    surface: str = Field(index=True)
    outcome: str = Field(index=True)
    started_at: str = Field(index=True)  # UTC ISO-8601
    kind: str = Field(index=True)
    released: bool = Field(default=False, index=True)
    tier_used: str | None = Field(default=None)
    est_cost_usd: float | None = Field(default=None)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class RawTranscriptRow(SQLModel, table=True):
    __tablename__ = "raw_transcript"  # type: ignore[assignment]
    id: str = Field(primary_key=True)
    compaction_id: str = Field(index=True)
    org_id: str = Field(index=True)
    object_key: str
    uploaded_at: str


class ActionQueueRow(SQLModel, table=True):
    """Pending org action awaiting human approval (seam; empty in v1)."""

    __tablename__ = "action_queue"  # type: ignore[assignment]
    id: str = Field(primary_key=True)
    action_id: str = Field(index=True)
    org_id: str = Field(index=True)
    team_id: str | None = Field(default=None, index=True)
    status: str = Field(index=True)
    created_at: str
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class OrgConsentRow(SQLModel, table=True):
    """Org/admin-level consent registry (seam)."""

    __tablename__ = "org_consent"  # type: ignore[assignment]
    id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    subject: str = Field(index=True)
    action_category: str = Field(index=True)
    state: str = Field(index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


SERVER_TABLES = [
    OrgRow,
    TeamRow,
    ActorRow,
    ReleasedCompactionRow,
    RawTranscriptRow,
    ActionQueueRow,
    OrgConsentRow,
]

__all__ = [
    "OrgRow",
    "TeamRow",
    "ActorRow",
    "ReleasedCompactionRow",
    "RawTranscriptRow",
    "ActionQueueRow",
    "OrgConsentRow",
    "SERVER_TABLES",
]
