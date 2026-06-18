"""Server: auth, ingestion, raw release, k-anonymity, founder query.

Runs on in-memory SQLite + in-memory object store + a scripted LLM provider, so
no Postgres/MinIO/model access is needed.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from manthana.schemas import EngineeringCompaction, Outcome, Surface
from manthana.server import ServerConfig, ServerStore, create_app
from manthana.server.auth import AuthError, issue_team_token, verify_team_token
from manthana.server.llm import ScriptedProvider
from manthana.server.storage import InMemoryObjectStore

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
ADMIN = {"X-Admin-Token": "adm"}


def _comp(cid: str, actor: str, project: str = "demo") -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=cid,
        actor=actor,
        surface=Surface.claude_code,
        project=project,
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent=f"intent {cid}",
        approach="a",
        outcome=Outcome.success,
        est_cost_usd=0.5,
        tier_used="opus",
        released=True,
    )


def _make(provider: ScriptedProvider | None = None):
    config = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    store = ServerStore.open("sqlite://")
    obj = InMemoryObjectStore()
    client = TestClient(create_app(config, store, obj, provider or ScriptedProvider([])))
    return client, config, store, obj


def _seed_contributors(store: ServerStore, n: int, org: str = "o1") -> None:
    store.create_org(org, "Org")
    for i in range(n):
        store.ingest_compaction(_comp(f"c{i}", f"e{i}@x.com"), org_id=org, team_id="t1")


def _team_auth(org: str = "o1", team: str = "t1", actor: str = "e@x.com") -> dict[str, str]:
    token = issue_team_token("x" * 40, org_id=org, team_id=team, actor=actor)
    return {"Authorization": f"Bearer {token}"}


# ── auth + bootstrap + ingestion ──────────────────────────────────────────
def test_health() -> None:
    client, *_ = _make()
    assert client.get("/healthz").json() == {"status": "ok"}


def test_admin_endpoints_require_admin_token() -> None:
    client, *_ = _make()
    assert client.post("/v1/admin/orgs", json={"org_id": "o", "name": "n"}).status_code == 401


def test_bootstrap_mint_token_and_ingest() -> None:
    client, *_ = _make()
    assert client.post(
        "/v1/admin/orgs", json={"org_id": "o1", "name": "O"}, headers=ADMIN
    ).is_success
    assert client.post(
        "/v1/admin/teams", json={"team_id": "t1", "org_id": "o1", "name": "T"}, headers=ADMIN
    ).is_success
    token = client.post(
        "/v1/admin/tokens",
        json={"org_id": "o1", "team_id": "t1", "actor": "e@x.com"},
        headers=ADMIN,
    ).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/v1/compactions",
        json={"compactions": [_comp("c1", "e@x.com").model_dump(mode="json")]},
        headers=auth,
    )
    assert resp.json() == {"ingested": 1}


def test_ingest_requires_team_token() -> None:
    client, *_ = _make()
    assert client.post("/v1/compactions", json={"compactions": []}).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.post("/v1/compactions", json={"compactions": []}, headers=bad).status_code == 401


def test_token_verification_rejects_wrong_secret() -> None:
    token = issue_team_token("secret-a" * 4, org_id="o", team_id="t", actor="e")
    try:
        verify_team_token("secret-b" * 4, token)
    except AuthError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected AuthError")


# ── raw transcript release ────────────────────────────────────────────────
def test_raw_release_stores_object_and_404s_unknown() -> None:
    client, _config, store, obj = _make()
    store.create_org("o1", "O")
    store.ingest_compaction(_comp("c1", "e@x.com"), org_id="o1", team_id="t1")
    auth = _team_auth()
    resp = client.post("/v1/compactions/c1/raw", json={"content": "l1\nl2"}, headers=auth)
    key = resp.json()["object_key"]
    assert obj.get(key) == b"l1\nl2"
    ghost = client.post("/v1/compactions/ghost/raw", json={"content": "x"}, headers=auth)
    assert ghost.status_code == 404


# ── founder query ─────────────────────────────────────────────────────────
def test_founder_query_grounded_with_citations() -> None:
    provider = ScriptedProvider(['{"project": "demo"}', "Shipped fixes [c1] and tests [c2]."])
    client, _config, store, _obj = _make(provider)
    _seed_contributors(store, 4)  # >= k-anon floor
    result = client.post(
        "/v1/founder/query", json={"org_id": "o1", "query": "what shipped?"}, headers=ADMIN
    ).json()
    assert result["insufficient_data"] is False
    assert result["rollup"]["distinct_contributors"] == 4
    assert set(result["citations"]) == {"c1", "c2"}
    assert "[c1]" in result["narrative"]


def test_founder_query_k_anonymity_suppresses_small_groups() -> None:
    provider = ScriptedProvider(["{}", "unused"])
    client, _config, store, _obj = _make(provider)
    _seed_contributors(store, 2)  # below floor of 4
    result = client.post(
        "/v1/founder/query", json={"org_id": "o1", "query": "what shipped?"}, headers=ADMIN
    ).json()
    assert result["insufficient_data"] is True
    assert result["rollup"] is None
    assert result["narrative"] == "insufficient data"


def test_founder_query_ungrounded_narrative_is_withheld() -> None:
    provider = ScriptedProvider(["{}", "Everything went great overall."])  # no [id] citations
    client, _config, store, _obj = _make(provider)
    _seed_contributors(store, 4)
    result = client.post(
        "/v1/founder/query", json={"org_id": "o1", "query": "summary"}, headers=ADMIN
    ).json()
    assert result["insufficient_data"] is True
    assert result["citations"] == []
    assert result["rollup"] is not None  # factual rollup still returned


def test_founder_query_requires_admin() -> None:
    client, *_ = _make()
    assert client.post("/v1/founder/query", json={"org_id": "o1", "query": "x"}).status_code == 401
