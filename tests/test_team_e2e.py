"""End-to-end multi-contributor proof (the point of the org layer).

Four engineers, each with their own team JWT, push released compactions to ONE
org over the real HTTP endpoints; cross-engineer skill mining then clears the
k-anonymity floor and drops contributor names. A 3-contributor variant stays
suppressed. (The agent-side SyncClient → server leg is covered by test_sync.py;
here we POST the same payload directly with each engineer's token.)

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from manthana.schemas import EngineeringCompaction, Outcome, Surface
from manthana.server import ServerConfig, ServerStore, create_app
from manthana.server.auth import issue_team_token
from manthana.server.llm import MockProvider
from manthana.server.storage import InMemoryObjectStore

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_SECRET = "x" * 40
_INTENT = "fix a flaky pytest timeout in CI by raising the asyncio wait budget"


def _make() -> tuple[TestClient, ServerConfig]:
    config = ServerConfig(jwt_secret=_SECRET, admin_token="adm")  # k_anon_floor defaults to 4
    store = ServerStore.open("sqlite://")
    store.create_org("acme", "Acme")
    store.create_team("platform", "acme", "Platform")
    client = TestClient(create_app(config, store, InMemoryObjectStore(), MockProvider("{}")))
    return client, config


def _payload(cid: str, actor: str) -> dict[str, Any]:
    return EngineeringCompaction(
        id=cid,
        session_id=cid,
        actor=actor,
        surface=Surface.claude_code,
        project="ci",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent=_INTENT,
        approach="raised the wait budget and de-flaked the fixture",
        outcome=Outcome.success,
        est_cost_usd=0.5,
        tier_used="opus",
        released=True,
    ).model_dump(mode="json")


def _push(client: TestClient, actor: str, cid: str) -> None:
    token = issue_team_token(_SECRET, org_id="acme", team_id="platform", actor=actor)
    resp = client.post(
        "/v1/compactions",
        json={"compactions": [_payload(cid, actor)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def _mine(client: TestClient) -> dict[str, Any]:
    resp = client.post(
        "/v1/admin/mine-skills", json={"org_id": "acme"}, headers={"X-Admin-Token": "adm"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_four_contributors_clear_k_anon_and_drop_names() -> None:
    client, _ = _make()
    actors = [f"eng{i}@acme.com" for i in range(4)]
    for i, actor in enumerate(actors):
        _push(client, actor, f"c{i}")

    result = _mine(client)
    assert result["queued"] >= 1
    assert len(result["proposals"]) >= 1
    proposal = result["proposals"][0]
    assert proposal["contributor_count"] == 4  # all four counted

    # k-anonymity: NO contributor identity appears anywhere in the org output.
    blob = json.dumps(result)
    for actor in actors:
        assert actor not in blob


def test_three_contributors_suppressed() -> None:
    client, _ = _make()
    for i in range(3):  # below the k-anon floor of 4
        _push(client, f"eng{i}@acme.com", f"c{i}")
    assert _mine(client)["proposals"] == []


def test_one_engineers_many_sessions_do_not_clear_floor() -> None:
    # 4 sessions but ONE contributor must NOT clear the floor (it's about people).
    client, _ = _make()
    for i in range(4):
        _push(client, "solo@acme.com", f"c{i}")
    assert _mine(client)["proposals"] == []


def test_forged_actors_in_payload_cannot_fake_k_anon() -> None:
    # One engineer (one token) submits compactions whose payload claims 4 DIFFERENT
    # actors. The server must bind each to the token's identity, so k-anon still
    # sees a single contributor and suppresses — no spoofing past the floor.
    client, _ = _make()
    attacker = issue_team_token(
        _SECRET, org_id="acme", team_id="platform", actor="mallory@acme.com"
    )
    for i in range(4):
        forged = _payload(f"c{i}", f"victim{i}@acme.com")  # lying about the contributor
        resp = client.post(
            "/v1/compactions",
            json={"compactions": [forged]},
            headers={"Authorization": f"Bearer {attacker}"},
        )
        assert resp.status_code == 200
    assert _mine(client)["proposals"] == []  # bound to mallory → 1 contributor → suppressed
