"""Local store round-trip + migration tests.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from manthana.agent.store import Store
from manthana.agent.store.engine import create_db_engine
from manthana.agent.store.migrations import run_migrations
from manthana.schemas import (
    EngineeringCompaction,
    Mode,
    Outcome,
    Role,
    Session,
    Surface,
    Turn,
)

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> Store:
    return Store.open_memory()


def _session(session_id: str = "s1", mode: Mode = Mode.work) -> Session:
    return Session(
        id=session_id,
        actor="eng@example.com",
        surface=Surface.claude_code,
        project="demo",
        repo_root="/repo/demo",
        started_at=_T0,
        mode=mode,
        turn_count=2,
    )


def _turn(session_id: str, seq: int, role: Role = Role.user) -> Turn:
    return Turn(
        id=f"{session_id}-t{seq}",
        session_id=session_id,
        actor="eng@example.com",
        seq=seq,
        role=role,
        content=f"turn {seq}",
        tool_input={"k": "v"} if role is Role.assistant else None,
    )


def _engineering(cid: str = "c1", session_id: str = "s1") -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=session_id,
        actor="eng@example.com",
        surface=Surface.claude_code,
        project="demo",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=42.0,
        task_intent="ship phase 1",
        approach="sqlmodel store",
        outcome=Outcome.success,
        tier_used="opus",
        est_cost_usd=0.12,
        files_touched=["store.py"],
        languages=["python"],
    )


def test_session_roundtrip(store: Store) -> None:
    store.upsert_session(_session())
    got = store.get_session("s1")
    assert got is not None
    assert got == _session()  # full Pydantic equality via data column


def test_session_upsert_is_idempotent_and_updates(store: Store) -> None:
    store.upsert_session(_session())
    store.upsert_session(_session())  # same id -> merge, not duplicate
    assert len(store.list_sessions()) == 1
    assert store.set_session_mode("s1", Mode.personal) is True
    assert store.get_session("s1").mode is Mode.personal  # type: ignore[union-attr]


def test_list_sessions_filters(store: Store) -> None:
    store.upsert_session(_session("s1"))
    store.upsert_session(_session("s2", mode=Mode.personal))
    assert {s.id for s in store.list_sessions(mode=Mode.work)} == {"s1"}
    assert {s.id for s in store.list_sessions(mode=Mode.personal)} == {"s2"}
    assert {s.id for s in store.list_sessions(project="demo")} == {"s1", "s2"}
    assert store.list_sessions(actor="nobody") == []


def test_turns_roundtrip_ordered(store: Store) -> None:
    store.upsert_session(_session())
    n = store.add_turns([_turn("s1", 2, Role.assistant), _turn("s1", 1)])
    assert n == 2
    turns = store.get_turns("s1")
    assert [t.seq for t in turns] == [1, 2]  # ordered by seq
    assert turns[1].tool_input == {"k": "v"}
    assert store.count_turns("s1") == 2


def test_compaction_polymorphic_roundtrip(store: Store) -> None:
    store.upsert_compaction(_engineering())
    got = store.get_compaction("c1")
    assert isinstance(got, EngineeringCompaction)
    assert got.files_touched == ["store.py"]
    assert got.tier_used == "opus"


def test_mark_released_updates_column_and_data(store: Store) -> None:
    store.upsert_compaction(_engineering())
    assert store.list_compactions(released=True) == []
    assert store.mark_released("c1", released=True, released_at=_T0) is True
    released = store.list_compactions(released=True)
    assert len(released) == 1
    assert released[0].released is True
    assert released[0].released_at == _T0


def test_migrations_idempotent() -> None:
    engine = create_db_engine(":memory:")
    assert run_migrations(engine) == [1]
    assert run_migrations(engine) == [1]  # re-run applies nothing new


def test_missing_rows_return_none(store: Store) -> None:
    assert store.get_session("ghost") is None
    assert store.get_compaction("ghost") is None
    assert store.set_session_mode("ghost", Mode.work) is False
    assert store.mark_released("ghost") is False
