"""ServerStore — multi-tenant persistence for the org server.

Same document-store pattern as the local store (typed index columns +
authoritative ``data`` JSON; UTC-normalized timestamps for correct ordering).

Tenant isolation (defense-in-depth, post-review):
  * Stored primary keys are **org-namespaced** (``org::id``) so a compaction id
    from one org can never collide with / overwrite another org's row.
  * Reads are **org-scoped** (and ``get_owned_*`` also team-scoped).
  * The server is **fail-closed on release**: only ``released=True`` compactions
    are stored as released and only released rows are ever returned.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from manthana.schemas import BaseCompaction, CompactionAdapter
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from .db import create_db_engine, init_db
from .tables import (
    ActionQueueRow,
    ActorRow,
    OrgConsentRow,
    OrgRow,
    RawTranscriptRow,
    ReleasedCompactionRow,
    TeamRow,
)


class NotReleasedError(ValueError):
    """Raised when an unreleased compaction is offered to the server."""


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pk(org_id: str, compaction_id: str) -> str:
    """Org-namespaced primary key (prevents cross-tenant id collisions)."""
    return f"{org_id}::{compaction_id}"


def _normalize_since(since: str | None) -> str | None:
    if since is None:
        return None
    if "T" not in since and len(since) == 10:
        return f"{since}T00:00:00+00:00"
    return since


def _until_bound(until: str | None) -> tuple[str, str] | None:
    """Return (operator, value) for the upper bound: half-open '<' for a
    date-only bound (so the whole boundary day is included), inclusive '<='
    for a full timestamp."""
    if until is None:
        return None
    if "T" not in until and len(until) == 10:
        try:
            nxt = date.fromisoformat(until) + timedelta(days=1)
            return ("<", f"{nxt.isoformat()}T00:00:00+00:00")
        except ValueError:
            return ("<=", until)
    return ("<=", until)


class ServerStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def open(cls, db_url: str) -> ServerStore:
        engine = create_db_engine(db_url)
        init_db(engine)
        return cls(engine)

    def ping(self) -> bool:
        """Lightweight DB connectivity check for the /readyz probe."""
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - any DB error means not-ready
            return False

    # ── tenancy ──────────────────────────────────────────────────────────
    def create_org(self, org_id: str, name: str) -> None:
        with DBSession(self._engine) as db:
            db.merge(OrgRow(id=org_id, name=name, created_at=_now_iso()))
            db.commit()

    def create_team(self, team_id: str, org_id: str, name: str) -> None:
        with DBSession(self._engine) as db:
            db.merge(TeamRow(id=team_id, org_id=org_id, name=name))
            db.commit()

    def upsert_actor(
        self, actor_id: str, org_id: str, team_id: str, display_name: str | None = None
    ) -> None:
        with DBSession(self._engine) as db:
            db.merge(
                ActorRow(id=actor_id, org_id=org_id, team_id=team_id, display_name=display_name)
            )
            db.commit()

    def get_org(self, org_id: str) -> OrgRow | None:
        with DBSession(self._engine) as db:
            return db.get(OrgRow, org_id)

    def list_orgs(self) -> list[OrgRow]:
        with DBSession(self._engine) as db:
            return list(db.exec(select(OrgRow)))

    def list_teams(self, org_id: str) -> list[TeamRow]:
        with DBSession(self._engine) as db:
            return list(db.exec(select(TeamRow).where(TeamRow.org_id == org_id)))

    def count_compactions(self, org_id: str) -> int:
        with DBSession(self._engine) as db:
            rows = db.exec(
                select(ReleasedCompactionRow.id)
                .where(ReleasedCompactionRow.org_id == org_id)
                .where(ReleasedCompactionRow.released == True)  # noqa: E712 - SQL boolean column
            )
            return len(list(rows))

    # ── ingestion (fail-closed on release; org-namespaced PK) ─────────────
    def ingest_compaction(
        self, compaction: BaseCompaction, *, org_id: str, team_id: str
    ) -> None:
        if not compaction.released:
            raise NotReleasedError(f"compaction {compaction.id} is not released")
        self.upsert_actor(compaction.actor, org_id, team_id)
        with DBSession(self._engine) as db:
            db.merge(
                ReleasedCompactionRow(
                    id=_pk(org_id, compaction.id),
                    org_id=org_id,
                    team_id=team_id,
                    actor=compaction.actor,
                    project=compaction.project,
                    surface=str(compaction.surface),
                    outcome=str(compaction.outcome),
                    started_at=_utc_iso(compaction.started_at),
                    kind=compaction.kind,
                    released=True,
                    tier_used=compaction.tier_used,
                    est_cost_usd=compaction.est_cost_usd,
                    data=compaction.model_dump(mode="json"),
                )
            )
            db.commit()

    def get_compaction(self, compaction_id: str, org_id: str) -> BaseCompaction | None:
        """Org-scoped fetch of a released compaction."""
        with DBSession(self._engine) as db:
            row = db.get(ReleasedCompactionRow, _pk(org_id, compaction_id))
            if row is None or not row.released:
                return None
            return CompactionAdapter.validate_python(row.data)

    def get_owned_compaction(
        self, compaction_id: str, org_id: str, team_id: str
    ) -> BaseCompaction | None:
        """Fetch a released compaction only if it belongs to this org AND team."""
        with DBSession(self._engine) as db:
            row = db.get(ReleasedCompactionRow, _pk(org_id, compaction_id))
            if row is None or not row.released or row.team_id != team_id:
                return None
            return CompactionAdapter.validate_python(row.data)

    def query_compactions(
        self,
        *,
        org_id: str,
        team_id: str | None = None,
        project: str | None = None,
        outcome: str | None = None,
        actor: str | None = None,
        surface: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[BaseCompaction]:
        with DBSession(self._engine) as db:
            stmt = (
                select(ReleasedCompactionRow)
                .where(ReleasedCompactionRow.org_id == org_id)
                .where(ReleasedCompactionRow.released == True)  # noqa: E712 - SQL boolean column
            )
            if team_id is not None:
                stmt = stmt.where(ReleasedCompactionRow.team_id == team_id)
            if project is not None:
                stmt = stmt.where(ReleasedCompactionRow.project == project)
            if outcome is not None:
                stmt = stmt.where(ReleasedCompactionRow.outcome == outcome)
            if actor is not None:
                stmt = stmt.where(ReleasedCompactionRow.actor == actor)
            if surface is not None:
                stmt = stmt.where(ReleasedCompactionRow.surface == surface)
            since_norm = _normalize_since(since)
            if since_norm is not None:
                stmt = stmt.where(col(ReleasedCompactionRow.started_at) >= since_norm)
            bound = _until_bound(until)
            if bound is not None:
                op, value = bound
                column = col(ReleasedCompactionRow.started_at)
                stmt = stmt.where(column < value if op == "<" else column <= value)
            stmt = stmt.order_by(ReleasedCompactionRow.started_at.desc())  # type: ignore[attr-defined]
            if limit is not None:
                stmt = stmt.limit(limit)
            return [CompactionAdapter.validate_python(row.data) for row in db.exec(stmt)]

    # ── raw transcript release (org-namespaced; ownership enforced by caller) ─
    def record_raw(self, compaction_id: str, org_id: str, object_key: str) -> None:
        with DBSession(self._engine) as db:
            db.merge(
                RawTranscriptRow(
                    id=f"raw::{org_id}::{compaction_id}",
                    compaction_id=compaction_id,
                    org_id=org_id,
                    object_key=object_key,
                    uploaded_at=_now_iso(),
                )
            )
            db.commit()

    # ── action queue (seam) ──────────────────────────────────────────────
    def enqueue_action(
        self,
        *,
        action_id: str,
        org_id: str,
        payload: dict[str, Any],
        team_id: str | None = None,
    ) -> str:
        """Enqueue a pending org action (e.g. an auto-drafted skill) for approval."""
        queue_id = f"queue-{uuid.uuid4().hex[:12]}"
        with DBSession(self._engine) as db:
            db.merge(
                ActionQueueRow(
                    id=queue_id,
                    action_id=action_id,
                    org_id=org_id,
                    team_id=team_id,
                    status="pending",
                    created_at=_now_iso(),
                    data=payload,
                )
            )
            db.commit()
        return queue_id

    def list_queue(self, org_id: str, *, status: str = "pending") -> list[ActionQueueRow]:
        with DBSession(self._engine) as db:
            stmt = (
                select(ActionQueueRow)
                .where(ActionQueueRow.org_id == org_id)
                .where(ActionQueueRow.status == status)
            )
            return list(db.exec(stmt))

    # ── consent registry (seam) ──────────────────────────────────────────
    def set_consent(
        self, *, org_id: str, subject: str, action_category: str, state: str
    ) -> None:
        with DBSession(self._engine) as db:
            db.merge(
                OrgConsentRow(
                    id=f"{org_id}:{subject}:{action_category}",
                    org_id=org_id,
                    subject=subject,
                    action_category=action_category,
                    state=state,
                    data={"state": state},
                )
            )
            db.commit()


__all__ = ["ServerStore", "NotReleasedError"]
