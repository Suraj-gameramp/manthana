"""Regression tests for the adversarial-review findings (all 11 confirmed).

Each test pins a specific fixed bug so it cannot silently regress.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from manthana.agent.actions import Dispatcher
from manthana.agent.actions.base import ActionContext, ActionResult, TriggerEvent
from manthana.agent.capture import ingest_file
from manthana.agent.compactor import Compactor
from manthana.agent.cost import estimate_cost, resolve_tier
from manthana.agent.llm import MockProvider
from manthana.agent.store import Store
from manthana.collectors import sessionize
from manthana.schemas import (
    Action,
    ActionActor,
    ActionOutcome,
    ActionShape,
    ConsentClass,
    Outcome,
    Role,
    Session,
    Surface,
    Turn,
)

FIXTURE = str(Path(__file__).parent / "fixtures" / "claude_code" / "sample-session.jsonl")
_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _session(sid: str = "s1") -> Session:
    return Session(
        id=sid, actor="e", surface=Surface.claude_code, project="p", started_at=_T0, ended_at=_T0
    )


def _assistant(model: str, tokens_in: int = 0) -> Turn:
    return Turn(
        id="t",
        session_id="s",
        actor="e",
        seq=0,
        role=Role.assistant,
        model=model,
        tokens_in=tokens_in,
    )


# ── Finding 1: dispatcher must fail CLOSED on an unresolvable session ──────
class _Recorder:
    action = Action(
        id="rec",
        name="rec",
        shape=ActionShape.read,
        actor=ActionActor.engineer,
        consent_class=ConsentClass.silent,
    )

    def __init__(self) -> None:
        self.ran = False

    def handles(self, event: TriggerEvent) -> bool:
        return True

    def run(self, event: TriggerEvent, ctx: ActionContext) -> ActionResult:
        self.ran = True
        return ActionResult(ActionOutcome.fired, "ran")


def test_dispatch_fails_closed_on_unresolvable_session() -> None:
    store = Store.open_memory()
    rec = _Recorder()
    disp = Dispatcher(store, [rec])
    none_id = disp.dispatch(TriggerEvent(type="x", actor="e", session_id=None))
    unknown = disp.dispatch(TriggerEvent(type="x", actor="e", session_id="ghost"))
    assert none_id[0].outcome is ActionOutcome.suppressed
    assert none_id[0].trigger_condition == "session_unresolved"
    assert unknown[0].outcome is ActionOutcome.suppressed
    assert rec.ran is False  # handler.run NEVER reached


# ── Finding 2: sessionize splits even when a segment starts timestamp-less ──
def test_sessionize_splits_with_leading_timestampless_turns() -> None:
    def turn(i: int, ts: datetime | None) -> Turn:
        return Turn(
            id=f"t{i}", session_id="s", actor="e", seq=i, role=Role.user, content="x", timestamp=ts
        )

    turns = [
        turn(0, None),
        turn(1, None),
        turn(2, datetime(2026, 6, 14, 11, 0, tzinfo=UTC)),
        turn(3, datetime(2026, 6, 14, 11, 45, tzinfo=UTC)),  # 45-min gap
    ]
    out = sessionize(
        turns,
        surface=Surface.claude_code,
        actor="e",
        project="p",
        repo_root=None,
        base_session_id="s",
        source_path=None,
        fallback_time=_T0,
    )
    assert len(out) == 2  # gap split fires despite the leading timestamp-less turns


# ── Finding 3: re-ingest is idempotent (no phantom derived sessions) ────────
def test_reingest_is_idempotent() -> None:
    store = Store.open_memory()
    ingest_file(store, FIXTURE, actor="e")
    ingest_file(store, FIXTURE, actor="e")  # second pass must not accumulate
    assert {s.id for s in store.list_sessions(limit=100)} == {"sample-session", "sample-session.2"}
    assert store.delete_session_family("sample-session") > 0
    assert store.list_sessions() == []


# ── Finding 4: ordering is chronological across mixed UTC offsets ───────────
def test_list_sessions_orders_chronologically_across_offsets() -> None:
    store = Store.open_memory()
    plus5 = timezone(timedelta(hours=5))
    # 12:00+05:00 == 07:00Z (earlier); lexically it sorts AFTER 11:00Z though.
    early = _session("early").model_copy(
        update={"started_at": datetime(2026, 6, 14, 12, 0, tzinfo=plus5)}
    )
    late = _session("late").model_copy(
        update={"started_at": datetime(2026, 6, 14, 11, 0, tzinfo=UTC)}
    )
    store.upsert_session(early)
    store.upsert_session(late)
    assert [s.id for s in store.list_sessions()] == ["late", "early"]  # 11:00Z is newer


# ── Finding 5: _extract_json survives prose with stray braces ───────────────
def test_compactor_extracts_json_amid_prose_braces() -> None:
    raw = 'Here is a set {like this}: {"task_intent": "found it", "outcome": "success"}'
    comp = Compactor(MockProvider(raw)).compact(_session(), [])
    assert comp.task_intent == "found it"
    assert comp.outcome is Outcome.success


# ── Finding 6: unknown model prices as sonnet with a consistent tier ────────
def test_unknown_model_prices_as_sonnet_with_consistent_tier() -> None:
    cost = estimate_cost([_assistant("gpt-9000", tokens_in=1_000_000)])
    assert cost.usd == 3.0  # sonnet input rate
    assert cost.tier == "sonnet"  # matches the applied pricing, not None
    assert resolve_tier(None) is None  # no model -> None


# ── Finding 7: list fields drop booleans (bool is an int subclass) ──────────
def test_compactor_drops_booleans_from_list_fields() -> None:
    raw = json.dumps(
        {"task_intent": "x", "outcome": "success", "files_touched": [True, False, "real.py"]}
    )
    comp = Compactor(MockProvider(raw)).compact(_session(), [])
    assert comp.files_touched == ["real.py"]
