"""Deploy-facing server bits: /readyz probe + S3/MinIO endpoint config.

Hermetic — no Docker, no boto3 (the S3 store is exercised with an injected fake
client), no network.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from manthana.server import ServerConfig, ServerStore, create_app
from manthana.server.llm import MockProvider
from manthana.server.storage import InMemoryObjectStore, S3ObjectStore, make_object_store


def _client() -> tuple[TestClient, ServerStore]:
    config = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    store = ServerStore.open("sqlite://")
    client = TestClient(create_app(config, store, InMemoryObjectStore(), MockProvider("{}")))
    return client, store


# ── readiness / liveness ────────────────────────────────────────────────────
def test_readyz_ok_when_db_reachable() -> None:
    client, _ = _client()
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_healthz_liveness() -> None:
    client, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok"}


def test_store_ping_true_on_live_engine() -> None:
    _, store = _client()
    assert store.ping() is True


# ── S3 / MinIO endpoint config ──────────────────────────────────────────────
def test_config_reads_s3_endpoint_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANTHANA_SERVER_OBJECT_STORE", "s3")
    monkeypatch.setenv("MANTHANA_SERVER_S3_BUCKET", "manthana-raw")
    monkeypatch.setenv("MANTHANA_SERVER_S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("MANTHANA_SERVER_S3_ACCESS_KEY", "ak")
    monkeypatch.setenv("MANTHANA_SERVER_S3_SECRET_KEY", "sk")
    monkeypatch.setenv("MANTHANA_SERVER_ADMIN_TOKEN", "adm")  # non-default (rejection guard)
    monkeypatch.setenv("MANTHANA_SERVER_JWT_SECRET", "x" * 40)
    cfg = ServerConfig.from_env()
    assert cfg.object_store == "s3"
    assert cfg.s3_endpoint_url == "http://minio:9000"
    assert cfg.s3_access_key == "ak" and cfg.s3_secret_key == "sk"


class _FakeS3:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803 - boto3 kwargs
        self.store[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803 - boto3 kwargs
        data = self.store[(Bucket, Key)]

        class _Body:
            def read(self) -> bytes:
                return data

        return {"Body": _Body()}


def test_s3_object_store_roundtrips_with_injected_client() -> None:
    s3 = S3ObjectStore("bucket", client=_FakeS3())
    s3.put("raw/k", b"payload")
    assert s3.get("raw/k") == b"payload"
    assert s3.get("missing") is None


def test_make_object_store_memory_by_default() -> None:
    cfg = ServerConfig(jwt_secret="x" * 40, admin_token="adm")
    assert isinstance(make_object_store(cfg), InMemoryObjectStore)


def test_make_object_store_s3_requires_bucket() -> None:
    cfg = ServerConfig(jwt_secret="x" * 40, admin_token="adm", object_store="s3")
    with pytest.raises(ValueError):
        make_object_store(cfg)  # raises before any boto3 import
