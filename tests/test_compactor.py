"""Compactor tests (deterministic via MockProvider).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from manthana.agent.compact import compact_session
from manthana.agent.compactor import Compactor
from manthana.agent.llm import MockProvider
from manthana.agent.store import Store
from manthana.schemas import (
    EngineeringCompaction,
    FrictionCategory,
    Outcome,
    Role,
    Session,
    Surface,
    Turn,
)

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

_GOOD = json.dumps(
    {
        "task_intent": "fix parser bug",
        "approach": "read then patch",
        "artifacts": ["patch"],
        "outcome": "success",
        "reusable_pattern": True,
        "friction_points": [
            {"category": "tool_error", "description": "first read failed", "turn_refs": ["3"]}
        ],
        "files_touched": ["parser.py"],
        "languages": ["python"],
        "tests_added": ["test_parser"],
    }
)


def _session() -> Session:
    return Session(
        id="s1",
        actor="eng@example.com",
        surface=Surface.claude_code,
        project="demo",
        started_at=_T0,
        ended_at=_T0 + timedelta(seconds=300),
        turn_count=2,
    )


def _turns() -> list[Turn]:
    return [
        Turn(id="t0", session_id="s1", actor="e", seq=0, role=Role.user, content="fix the parser"),
        Turn(
            id="t1",
            session_id="s1",
            actor="e",
            seq=1,
            role=Role.assistant,
            content="done",
            model="claude-opus-4-8",
            tokens_in=1_000_000,
            tokens_out=0,
        ),
    ]


def test_compact_produces_engineering_compaction() -> None:
    comp = Compactor(MockProvider(_GOOD)).compact(_session(), _turns())
    assert isinstance(comp, EngineeringCompaction)
    assert comp.kind == "engineering"
    assert comp.task_intent == "fix parser bug"
    assert comp.outcome is Outcome.success
    assert comp.reusable_pattern is True
    assert comp.files_touched == ["parser.py"]
    assert comp.friction_points[0].category is FrictionCategory.tool_error
    # cost/tier come from OUR token data, not the LLM
    assert comp.tier_used == "opus"
    assert comp.est_cost_usd == 15.0
    assert comp.duration_seconds == 300.0
    assert comp.prompt_version == "v0"
    assert comp.id == "comp-s1"


def test_malformed_output_falls_back_gracefully() -> None:
    comp = Compactor(MockProvider("not json at all")).compact(_session(), _turns())
    assert comp.outcome is Outcome.partial  # safe default
    assert comp.task_intent == "fix the parser"  # from first user turn
    assert comp.tier_used == "opus"  # cost still computed


def test_extract_json_tolerates_prose_and_fences() -> None:
    wrapped = f"Sure, here is the digest:\n```json\n{_GOOD}\n```\nHope that helps!"
    comp = Compactor(MockProvider(wrapped)).compact(_session(), _turns())
    assert comp.outcome is Outcome.success
    assert comp.task_intent == "fix parser bug"


def test_compact_session_persists_to_store() -> None:
    store = Store.open_memory()
    store.upsert_session(_session())
    store.add_turns(_turns())
    comp = compact_session(store, "s1", provider=MockProvider(_GOOD))
    assert comp is not None
    fetched = store.get_compaction("comp-s1")
    assert isinstance(fetched, EngineeringCompaction)
    assert fetched.files_touched == ["parser.py"]


def test_compact_session_unknown_returns_none() -> None:
    store = Store.open_memory()
    assert compact_session(store, "ghost", provider=MockProvider(_GOOD)) is None
