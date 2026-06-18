"""Regression tests for the server adversarial-review findings.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from manthana.schemas import EngineeringCompaction, Outcome, Surface
from manthana.server import ServerConfig, ServerStore, create_app
from manthana.server.auth import ALGORITHM, AuthError, issue_team_token, verify_team_token
from manthana.server.config import ServerConfig as Cfg
from manthana.server.founder import run_query
from manthana.server.llm import ScriptedProvider
from manthana.server.storage import InMemoryObjectStore
from manthana.server.store import NotReleasedError

_T0 = datetime(2026, 3, 15, 8, 30, tzinfo=UTC)
ADMIN = {"X-Admin-Token": "adm"}


def _comp(
    cid: str,
    actor: str,
    *,
    project: str = "demo",
    released: bool = True,
    started: datetime = _T0,
) -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=cid,
        actor=actor,
        surface=Surface.claude_code,
        project=project,
        started_at=started,
        ended_at=started,
        duration_seconds=1.0,
        task_intent=f"intent {cid}",
        approach="a",
        outcome=Outcome.success,
        est_cost_usd=0.5,
        released=released,
    )


def _store() -> ServerStore:
    store = ServerStore.open("sqlite://")
    store.create_org("orgA", "A")
    store.create_org("orgB", "B")
    return store


def _auth(org: str, team: str, actor: str) -> dict[str, str]:
    token = issue_team_token("x" * 40, org_id=org, team_id=team, actor=actor)
    return {"Authorization": f"Bearer {token}"}


# ── Finding 1: cross-tenant compaction isolation (namespaced PK) ───────────
def test_cross_tenant_compaction_isolation() -> None:
    store = _store()
    store.ingest_compaction(_comp("shared", "b@x.com"), org_id="orgB", team_id="tB")
    # org A ingests a compaction whose id collides — must NOT touch org B's row.
    store.ingest_compaction(_comp("shared", "a@x.com"), org_id="orgA", team_id="tA")
    b = store.query_compactions(org_id="orgB")
    a = store.query_compactions(org_id="orgA")
    assert [c.actor for c in b] == ["b@x.com"]  # org B intact
    assert [c.actor for c in a] == ["a@x.com"]
    assert store.get_compaction("shared", "orgB") is not None
    # org A cannot read org B's compaction
    assert store.get_owned_compaction("shared", "orgA", "tA").actor == "a@x.com"  # type: ignore[union-attr]


# ── Finding 2: cross-tenant raw upload is 404 ──────────────────────────────
def test_cross_tenant_raw_upload_is_rejected() -> None:
    config = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    store = _store()
    obj = InMemoryObjectStore()
    client = TestClient(create_app(config, store, obj, ScriptedProvider([])))
    store.ingest_compaction(_comp("victim", "b@x.com"), org_id="orgB", team_id="tB")
    attacker = _auth("orgA", "tA", "a@x.com")
    resp = client.post("/v1/compactions/victim/raw", json={"content": "x"}, headers=attacker)
    assert resp.status_code == 404  # cannot touch org B's compaction
    assert obj.get("orgA/tA/victim.jsonl") is None


# ── Findings 3+4: fail-closed on release ───────────────────────────────────
def test_unreleased_compaction_rejected_at_store() -> None:
    store = _store()
    with pytest.raises(NotReleasedError):
        store.ingest_compaction(_comp("u1", "a@x.com", released=False), org_id="orgA", team_id="tA")


def test_unreleased_compaction_rejected_at_api() -> None:
    config = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    store = _store()
    client = TestClient(create_app(config, store, InMemoryObjectStore(), ScriptedProvider([])))
    auth = _auth("orgA", "tA", "a@x.com")
    body = {"compactions": [_comp("u1", "a@x.com", released=False).model_dump(mode="json")]}
    assert client.post("/v1/compactions", json=body, headers=auth).status_code == 422


# ── Finding 5: until date boundary (same-day query returns rows) ───────────
def test_until_date_includes_whole_boundary_day() -> None:
    store = _store()
    for i, hour in enumerate((0, 8, 23)):
        ts = datetime(2026, 3, 15, hour, 0, tzinfo=UTC)
        store.ingest_compaction(
            _comp(f"c{i}", f"e{i}@x.com", started=ts), org_id="orgA", team_id="tA"
        )
    same_day = store.query_compactions(org_id="orgA", since="2026-03-15", until="2026-03-15")
    assert len(same_day) == 3  # all three same-day rows, not []


# ── Finding 6: per-bucket k-anonymity ──────────────────────────────────────
def test_per_bucket_k_anon_suppresses_single_contributor_project() -> None:
    config = Cfg(k_anon_floor=4)
    store = _store()
    for i in range(4):  # 4 contributors on "shared"
        store.ingest_compaction(
            _comp(f"s{i}", f"e{i}@x.com", project="shared"), org_id="orgA", team_id="tA"
        )
    # one extra contributor on a solo project (raises global distinct to 5)
    store.ingest_compaction(
        _comp("solo", "solo@x.com", project="secret"), org_id="orgA", team_id="tA"
    )
    provider = ScriptedProvider(["{}", "Shared work progressed [s0]."])
    result = run_query(store, config, org_id="orgA", query="q", provider=provider)
    assert result.rollup is not None
    assert "shared" in result.rollup.by_project
    assert "secret" not in result.rollup.by_project  # single-contributor bucket suppressed


# ── Finding 8: JWT must carry exp ──────────────────────────────────────────
def test_jwt_without_exp_is_rejected() -> None:
    secret = "x" * 40
    token = jwt.encode(
        {"sub": "e", "org": "o", "team": "t", "scope": "agent"}, secret, algorithm=ALGORITHM
    )
    with pytest.raises(AuthError):
        verify_team_token(secret, token)


# ── Finding 9: invalid filter values are nulled (not silently empty) ───────
def test_invalid_filter_values_are_nulled() -> None:
    from manthana.server.founder import parse_filter

    provider = ScriptedProvider(['{"outcome": "successful", "surface": "cursor_ide"}'])
    spec = parse_filter("q", provider)
    assert spec.outcome is None  # "successful" is not a valid outcome
    assert spec.surface is None  # "cursor_ide" is not a valid surface
