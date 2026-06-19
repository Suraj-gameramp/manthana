"""Founder web console (server `/ui`): cookie-gated login, console, query, mine.

In-memory SQLite + in-memory object store + a deterministic provider — no
Postgres/MinIO/model access. Verifies the org-data gate (unauthenticated requests
redirect to login and expose nothing) alongside the happy paths.

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


def _comp(
    cid: str, actor: str, *, project: str = "demo", intent: str = "x"
) -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=cid,
        actor=actor,
        surface=Surface.claude_code,
        project=project,
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent=intent,
        approach="a",
        outcome=Outcome.success,
        est_cost_usd=0.5,
        tier_used="opus",
        released=True,
    )


def _make(provider: MockProvider | None = None) -> tuple[TestClient, ServerStore]:
    config = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    store = ServerStore.open("sqlite://")
    obj = InMemoryObjectStore()
    client = TestClient(
        create_app(config, store, obj, provider or MockProvider("narrative [c0]")),
        follow_redirects=False,
    )
    return client, store


def _seed(store: ServerStore, n: int, *, intent: str = "x", org: str = "o1") -> None:
    store.create_org(org, "Acme")
    store.create_team("t1", org, "Platform")
    for i in range(n):
        comp = _comp(f"c{i}", f"e{i}@x.com", intent=intent)
        store.ingest_compaction(comp, org_id=org, team_id="t1")


def _login(client: TestClient, token: str = "adm") -> None:
    client.post("/ui/login", data={"token": token})


# ── auth gate: unauthenticated requests redirect to login, expose nothing ──
def test_console_redirects_to_login_when_unauthenticated() -> None:
    client, store = _make()
    _seed(store, 1)
    resp = client.get("/ui")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/login"
    assert "Acme" not in resp.text  # no org data leaked to an anonymous caller


def test_query_and_mine_require_auth() -> None:
    client, store = _make()
    _seed(store, 4)
    q = client.post("/ui/query", data={"org_id": "o1", "query": "hi"})
    m = client.post("/ui/mine", data={"org_id": "o1"})
    assert q.status_code == 303 and q.headers["location"] == "/ui/login"
    assert m.status_code == 303 and m.headers["location"] == "/ui/login"
    assert store.list_queue("o1") == []  # mine did not run


def test_login_rejects_wrong_token() -> None:
    client, _ = _make()
    resp = client.post("/ui/login", data={"token": "nope"})
    assert resp.status_code == 401
    assert "Invalid admin token" in resp.text


# ── happy paths after login ────────────────────────────────────────────────
def test_login_sets_cookie_and_console_lists_orgs() -> None:
    client, store = _make()
    _seed(store, 2)
    login = client.post("/ui/login", data={"token": "adm"})
    assert login.status_code == 303
    assert "manthana_admin" in login.headers.get("set-cookie", "")
    body = client.get("/ui").text  # cookie now in the client jar
    assert "Acme" in body and "o1" in body
    assert "Mine org skills" in body


def test_query_renders_rollup_and_citation() -> None:
    client, store = _make(MockProvider("Engineers shipped work [c0]."))
    _seed(store, 4)  # >= k-anon floor (4) so the rollup is not suppressed
    _login(client)
    resp = client.post("/ui/query", data={"org_id": "o1", "query": "what shipped?"})
    assert resp.status_code == 200
    assert "sessions=4" in resp.text
    assert "c0" in resp.text  # the cited compaction surfaced


def test_query_below_k_anon_is_insufficient() -> None:
    client, store = _make()
    _seed(store, 2)  # below floor of 4
    _login(client)
    resp = client.post("/ui/query", data={"org_id": "o1", "query": "what shipped?"})
    assert resp.status_code == 200
    assert "insufficient data" in resp.text


def test_mine_enqueues_skill_proposal() -> None:
    client, store = _make(MockProvider("{}"))  # synthesis falls back to a deterministic draft
    _seed(store, 4, intent="fix flaky pytest timeout in CI")
    _login(client)
    resp = client.post("/ui/mine", data={"org_id": "o1"})
    assert resp.status_code == 303
    assert len(store.list_queue("o1")) >= 1  # a proposal was queued for approval


def test_logout_clears_cookie() -> None:
    client, store = _make()
    _seed(store, 1)
    _login(client)
    assert client.get("/ui").status_code == 200
    out = client.get("/ui/logout")
    assert out.status_code == 303 and out.headers["location"] == "/ui/login"
    client.cookies.clear()  # browser would drop the deleted cookie
    assert client.get("/ui").status_code == 303  # back to gated
