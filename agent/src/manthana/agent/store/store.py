"""``Store`` — the local-agent persistence API over SQLite.

CRUD/query surface re-expressed from affaan-m/ECC
``scripts/lib/state-store/{index,queries}.js`` (MIT, 2026 Affaan Mustafa): open
the database, run migrations, expose typed entity operations. Domain objects are
reconstructed from each row's authoritative ``data`` JSON, so the store never
duplicates the schema definitions in ``manthana.schemas``.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from manthana.schemas import (
    ActionAuditEntry,
    BaseCompaction,
    CompactionAdapter,
    ConsentEntry,
    Mode,
    Session,
    Turn,
)
from sqlalchemy.engine import Engine
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from .engine import MEMORY, create_db_engine
from .migrations import run_migrations
from .tables import ActionAuditRow, CompactionRow, ConsentRow, SessionRow, TurnRow


def _utc_iso(value: datetime) -> str:
    """UTC ISO-8601 for index columns, so lexical TEXT ordering is chronological."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _iso(value: datetime | None) -> str | None:
    return _utc_iso(value) if value is not None else None


def _session_row(session: Session) -> SessionRow:
    return SessionRow(
        id=session.id,
        actor=session.actor,
        surface=str(session.surface),
        project=session.project,
        mode=str(session.mode),
        started_at=_utc_iso(session.started_at),
        ended_at=_iso(session.ended_at),
        resumed_from=session.resumed_from,
        turn_count=session.turn_count,
        data=session.model_dump(mode="json"),
    )


def _turn_row(turn: Turn) -> TurnRow:
    return TurnRow(
        id=turn.id,
        session_id=turn.session_id,
        actor=turn.actor,
        seq=turn.seq,
        role=str(turn.role),
        timestamp=_iso(turn.timestamp),
        data=turn.model_dump(mode="json"),
    )


def _compaction_row(compaction: BaseCompaction) -> CompactionRow:
    return CompactionRow(
        id=compaction.id,
        session_id=compaction.session_id,
        actor=compaction.actor,
        project=compaction.project,
        surface=str(compaction.surface),
        kind=compaction.kind,
        outcome=str(compaction.outcome),
        released=compaction.released,
        started_at=_utc_iso(compaction.started_at),
        tier_used=compaction.tier_used,
        est_cost_usd=compaction.est_cost_usd,
        data=compaction.model_dump(mode="json"),
    )


class Store:
    """Local persistence for Turns, Sessions, and Compactions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def open(cls, db_path: str | Path | None = None) -> Store:
        """Open (creating + migrating) the store. Default path = local data home."""
        if db_path is None:
            from manthana.agent.datahome import db_path as default_db_path
            from manthana.agent.datahome import ensure_data_home

            ensure_data_home()
            db_path = default_db_path()
        engine = create_db_engine(db_path)
        run_migrations(engine)
        return cls(engine)

    @classmethod
    def open_memory(cls) -> Store:
        """Open an ephemeral in-memory store (tests)."""
        return cls.open(MEMORY)

    def close(self) -> None:
        self._engine.dispose()

    # ── sessions ─────────────────────────────────────────────────────────
    def upsert_session(self, session: Session) -> None:
        with DBSession(self._engine) as db:
            db.merge(_session_row(session))
            db.commit()

    def get_session(self, session_id: str) -> Session | None:
        with DBSession(self._engine) as db:
            row = db.get(SessionRow, session_id)
            return Session.model_validate(row.data) if row else None

    def list_sessions(
        self,
        *,
        actor: str | None = None,
        project: str | None = None,
        surface: str | None = None,
        mode: Mode | str | None = None,
        limit: int | None = None,
    ) -> list[Session]:
        with DBSession(self._engine) as db:
            stmt = select(SessionRow)
            if actor is not None:
                stmt = stmt.where(SessionRow.actor == actor)
            if project is not None:
                stmt = stmt.where(SessionRow.project == project)
            if surface is not None:
                stmt = stmt.where(SessionRow.surface == surface)
            if mode is not None:
                stmt = stmt.where(SessionRow.mode == str(mode))
            stmt = stmt.order_by(SessionRow.started_at.desc())  # type: ignore[attr-defined]
            if limit is not None:
                stmt = stmt.limit(limit)
            return [Session.model_validate(row.data) for row in db.exec(stmt)]

    def set_session_mode(self, session_id: str, mode: Mode) -> bool:
        with DBSession(self._engine) as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return False
            model = Session.model_validate(row.data)
            model.mode = mode
            db.merge(_session_row(model))
            db.commit()
            return True

    def delete_session_family(self, base_session_id: str) -> int:
        """Delete a base session, its derived split sessions (``base.2`` …), and
        all their turns + compactions — so re-ingesting a transcript is
        idempotent and never leaves stale/phantom rows. Returns rows removed.
        """
        family_like = f"{base_session_id}.%"
        removed = 0
        with DBSession(self._engine) as db:
            derived = db.exec(
                select(SessionRow).where(col(SessionRow.id).like(family_like))
            ).all()
            ids = [base_session_id, *(row.id for row in derived)]
            for sid in ids:
                for turn in db.exec(select(TurnRow).where(TurnRow.session_id == sid)).all():
                    db.delete(turn)
                    removed += 1
                for comp in db.exec(
                    select(CompactionRow).where(CompactionRow.session_id == sid)
                ).all():
                    db.delete(comp)
                    removed += 1
            for row in derived:
                db.delete(row)
                removed += 1
            base = db.get(SessionRow, base_session_id)
            if base is not None:
                db.delete(base)
                removed += 1
            db.commit()
        return removed

    def update_session_tags(self, session_id: str, tags: dict[str, str]) -> bool:
        with DBSession(self._engine) as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return False
            model = Session.model_validate(row.data)
            model.tags = tags
            db.merge(_session_row(model))
            db.commit()
            return True

    # ── turns ────────────────────────────────────────────────────────────
    def add_turns(self, turns: Iterable[Turn]) -> int:
        count = 0
        with DBSession(self._engine) as db:
            for turn in turns:
                db.merge(_turn_row(turn))
                count += 1
            db.commit()
        return count

    def get_turns(self, session_id: str) -> list[Turn]:
        with DBSession(self._engine) as db:
            stmt = (
                select(TurnRow)
                .where(TurnRow.session_id == session_id)
                .order_by(TurnRow.seq.asc())  # type: ignore[attr-defined]
            )
            return [Turn.model_validate(row.data) for row in db.exec(stmt)]

    def count_turns(self, session_id: str) -> int:
        return len(self.get_turns(session_id))

    # ── compactions ──────────────────────────────────────────────────────
    def upsert_compaction(self, compaction: BaseCompaction) -> None:
        with DBSession(self._engine) as db:
            db.merge(_compaction_row(compaction))
            db.commit()

    def get_compaction(self, compaction_id: str) -> BaseCompaction | None:
        with DBSession(self._engine) as db:
            row = db.get(CompactionRow, compaction_id)
            return CompactionAdapter.validate_python(row.data) if row else None

    def list_compactions(
        self,
        *,
        actor: str | None = None,
        project: str | None = None,
        released: bool | None = None,
        outcome: str | None = None,
        limit: int | None = None,
    ) -> list[BaseCompaction]:
        with DBSession(self._engine) as db:
            stmt = select(CompactionRow)
            if actor is not None:
                stmt = stmt.where(CompactionRow.actor == actor)
            if project is not None:
                stmt = stmt.where(CompactionRow.project == project)
            if released is not None:
                stmt = stmt.where(CompactionRow.released == released)
            if outcome is not None:
                stmt = stmt.where(CompactionRow.outcome == outcome)
            stmt = stmt.order_by(CompactionRow.started_at.desc())  # type: ignore[attr-defined]
            if limit is not None:
                stmt = stmt.limit(limit)
            return [CompactionAdapter.validate_python(row.data) for row in db.exec(stmt)]

    def mark_released(
        self, compaction_id: str, *, released: bool = True, released_at: datetime | None = None
    ) -> bool:
        with DBSession(self._engine) as db:
            row = db.get(CompactionRow, compaction_id)
            if row is None:
                return False
            model = CompactionAdapter.validate_python(row.data)
            model.released = released
            model.released_at = released_at
            db.merge(_compaction_row(model))
            db.commit()
            return True

    # ── action audit log (seam) ──────────────────────────────────────────
    def add_audit(self, entry: ActionAuditEntry) -> None:
        with DBSession(self._engine) as db:
            db.merge(
                ActionAuditRow(
                    id=entry.id,
                    action_id=entry.action_id,
                    actor=entry.actor,
                    fired_at=_utc_iso(entry.fired_at),
                    outcome=str(entry.outcome),
                    data=entry.model_dump(mode="json"),
                )
            )
            db.commit()

    def list_audit(
        self,
        *,
        action_id: str | None = None,
        actor: str | None = None,
        limit: int | None = None,
    ) -> list[ActionAuditEntry]:
        with DBSession(self._engine) as db:
            stmt = select(ActionAuditRow)
            if action_id is not None:
                stmt = stmt.where(ActionAuditRow.action_id == action_id)
            if actor is not None:
                stmt = stmt.where(ActionAuditRow.actor == actor)
            stmt = stmt.order_by(ActionAuditRow.fired_at.desc())  # type: ignore[attr-defined]
            if limit is not None:
                stmt = stmt.limit(limit)
            return [ActionAuditEntry.model_validate(row.data) for row in db.exec(stmt)]

    def last_fired_at(self, action_id: str, actor: str | None) -> datetime | None:
        """Most recent successful fire time for cooldown checks."""
        with DBSession(self._engine) as db:
            stmt = (
                select(ActionAuditRow.fired_at)
                .where(ActionAuditRow.action_id == action_id)
                .where(ActionAuditRow.actor == actor)
                .where(ActionAuditRow.outcome == "fired")
                .order_by(ActionAuditRow.fired_at.desc())  # type: ignore[attr-defined]
                .limit(1)
            )
            value = db.exec(stmt).first()
            return datetime.fromisoformat(value) if value else None

    # ── consent registry (seam) ──────────────────────────────────────────
    def set_consent(self, entry: ConsentEntry) -> None:
        with DBSession(self._engine) as db:
            db.merge(
                ConsentRow(
                    id=entry.id,
                    subject=entry.subject,
                    action_category=entry.action_category,
                    state=str(entry.state),
                    data=entry.model_dump(mode="json"),
                )
            )
            db.commit()

    def get_consent(self, subject: str, action_category: str) -> ConsentEntry | None:
        with DBSession(self._engine) as db:
            stmt = (
                select(ConsentRow)
                .where(ConsentRow.subject == subject)
                .where(ConsentRow.action_category == action_category)
                .limit(1)
            )
            row = db.exec(stmt).first()
            return ConsentEntry.model_validate(row.data) if row else None

    def list_consent(self) -> list[ConsentEntry]:
        with DBSession(self._engine) as db:
            return [ConsentEntry.model_validate(r.data) for r in db.exec(select(ConsentRow))]


__all__ = ["Store"]
