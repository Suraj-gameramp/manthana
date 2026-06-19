"""Server org skill-mining endpoint (k-anonymized cross-engineer).

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from manthana.schemas import EngineeringCompaction, Outcome, Surface
from manthana.server import ServerConfig, ServerStore, create_app
from manthana.server.llm import MockProvider
from manthana.server.storage import InMemoryObjectStore

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
ADMIN = {"X-Admin-Token": "adm"}


def _released(cid: str, actor: str, intent: str) -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=cid,
        actor=actor,
        surface=Surface.claude_code,
        project="demo",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent=intent,
        approach="a",
        outcome=Outcome.success,
        released=True,
    )


def _app() -> tuple[TestClient, ServerStore]:
    config = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    store = ServerStore.open("sqlite://")
    store.create_org("o1", "O")
    client = TestClient(create_app(config, store, InMemoryObjectStore(), MockProvider("{}")))
    return client, store


def _seed(store: ServerStore, n: int) -> None:
    for i in range(n):
        store.ingest_compaction(
            _released(f"c{i}", f"e{i}@x.com", "fix flaky pytest timeout"),
            org_id="o1",
            team_id="t1",
        )


def test_org_mining_proposes_and_queues_above_floor() -> None:
    client, store = _app()
    _seed(store, 4)  # 4 distinct contributors >= k-anon floor
    result = client.post("/v1/admin/mine-skills", json={"org_id": "o1"}, headers=ADMIN).json()
    assert result["queued"] >= 1
    assert result["proposals"][0]["contributor_count"] == 4
    assert len(store.list_queue("o1")) >= 1  # enqueued for approval (seam)


def test_org_mining_suppressed_below_floor() -> None:
    client, store = _app()
    _seed(store, 2)  # below the floor of 4
    result = client.post("/v1/admin/mine-skills", json={"org_id": "o1"}, headers=ADMIN).json()
    assert result["queued"] == 0


def test_org_mining_requires_admin() -> None:
    client, _store = _app()
    assert client.post("/v1/admin/mine-skills", json={"org_id": "o1"}).status_code == 401
