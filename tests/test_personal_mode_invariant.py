"""Personal-mode leak invariant.

This test MUST exist from commit one and pass before any sync code is merged
(manthana-decisions.md, "Test commitments"). Personal-mode sessions never leave
the laptop. Every path that releases data to the org routes through
``manthana.agent.sync.eligible_for_sync``; this test asserts that no
personal-mode compaction can pass that gate — even when explicitly released.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime

from manthana.agent.sync import eligible_for_sync, session_is_syncable
from manthana.schemas import BaseCompaction, Mode, Outcome, Session, Surface

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _session(session_id: str, mode: Mode) -> Session:
    return Session(
        id=session_id,
        actor="eng@example.com",
        surface=Surface.claude_code,
        project="demo",
        started_at=_T0,
        mode=mode,
    )


def _compaction(session_id: str, released: bool) -> BaseCompaction:
    return BaseCompaction(
        id=f"c-{session_id}-{int(released)}",
        session_id=session_id,
        actor="eng@example.com",
        surface=Surface.claude_code,
        project="demo",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent="t",
        approach="a",
        outcome=Outcome.success,
        released=released,
    )


def test_personal_session_is_never_syncable() -> None:
    assert session_is_syncable(_session("s", Mode.personal)) is False
    assert session_is_syncable(_session("s", Mode.work)) is True


def test_personal_compaction_never_syncs_even_when_released() -> None:
    sessions = {
        "work": _session("work", Mode.work),
        "personal": _session("personal", Mode.personal),
    }
    compactions = [
        _compaction("work", released=True),
        _compaction("personal", released=True),  # released BUT personal -> blocked
        _compaction("personal", released=False),
    ]
    out = eligible_for_sync(compactions, sessions)
    synced_sessions = {c.session_id for c in out}
    assert "personal" not in synced_sessions
    assert synced_sessions == {"work"}


def test_unreleased_work_compaction_does_not_sync() -> None:
    sessions = {"work": _session("work", Mode.work)}
    out = eligible_for_sync([_compaction("work", released=False)], sessions)
    assert out == []


def test_unknown_session_fails_closed() -> None:
    out = eligible_for_sync([_compaction("ghost", released=True)], {})
    assert out == []
