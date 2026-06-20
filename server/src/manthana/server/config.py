"""Server configuration (from ``MANTHANA_SERVER_*`` env vars).

Dev defaults run on SQLite + an in-memory object store with insecure secrets;
production MUST override JWT secret, admin token, DB URL, and object store.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

import os
from dataclasses import dataclass

K_ANON_FLOOR_DEFAULT = 4

# Insecure placeholders so `ServerConfig()` is constructible in a REPL/dev, but
# rejected at startup (see __post_init__) — a real deploy must override them.
_DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-me-in-production"  # noqa: S105 - placeholder
_DEV_ADMIN_TOKEN = "dev-admin-token"  # noqa: S105 - placeholder


@dataclass
class ServerConfig:
    db_url: str = "sqlite:///./manthana-server.db"
    jwt_secret: str = _DEV_JWT_SECRET
    admin_token: str = _DEV_ADMIN_TOKEN
    k_anon_floor: int = K_ANON_FLOOR_DEFAULT
    object_store: str = "memory"  # "memory" | "s3"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None  # set for MinIO / non-AWS S3
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    # Founder-narrative provider (arch §9): dev/tests use the deterministic mock;
    # the org sets llm_provider="anthropic" + ANTHROPIC_API_KEY for a real model.
    llm_provider: str = "mock"  # "mock" | "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 1024

    def __post_init__(self) -> None:
        # An empty admin token or JWT secret is an auth bypass: hmac.compare_digest
        # ("", "") is True, so an empty cookie/header would authenticate. Reject it
        # (the dev defaults above are non-empty; only an explicit "" override trips this).
        if not self.admin_token:
            raise ValueError("admin_token must not be empty (set MANTHANA_SERVER_ADMIN_TOKEN)")
        if not self.jwt_secret:
            raise ValueError("jwt_secret must not be empty (set MANTHANA_SERVER_JWT_SECRET)")
        # Fail closed on the shipped placeholders so a deploy can't silently run
        # with publicly-known secrets (anyone could mint admin/team tokens).
        if self.admin_token == _DEV_ADMIN_TOKEN or self.jwt_secret == _DEV_JWT_SECRET:
            raise ValueError(
                "refusing to run with the insecure dev defaults — set "
                "MANTHANA_SERVER_ADMIN_TOKEN and MANTHANA_SERVER_JWT_SECRET "
                "(copy .env.example to .env)"
            )
        if self.llm_provider not in ("mock", "anthropic"):
            raise ValueError(
                f"llm_provider must be 'mock' or 'anthropic', got {self.llm_provider!r}"
            )
        # A non-positive k-anon floor would silently disable the privacy floor; a
        # non-positive/absurd max_tokens is a config typo (0 → empty narrative,
        # huge → runaway cost). Note: llm_model is intentionally NOT whitelisted —
        # hardcoding model IDs would reject valid future models.
        if self.k_anon_floor < 1:
            raise ValueError(f"k_anon_floor must be >= 1, got {self.k_anon_floor}")
        if not 1 <= self.llm_max_tokens <= 100_000:
            raise ValueError(f"llm_max_tokens must be 1..100000, got {self.llm_max_tokens}")

    @classmethod
    def from_env(cls) -> ServerConfig:
        env = os.environ.get
        return cls(
            db_url=env("MANTHANA_SERVER_DB_URL", cls.db_url),
            jwt_secret=env("MANTHANA_SERVER_JWT_SECRET", cls.jwt_secret),
            admin_token=env("MANTHANA_SERVER_ADMIN_TOKEN", cls.admin_token),
            k_anon_floor=int(env("MANTHANA_SERVER_K_ANON", str(cls.k_anon_floor))),
            object_store=env("MANTHANA_SERVER_OBJECT_STORE", cls.object_store),
            s3_bucket=env("MANTHANA_SERVER_S3_BUCKET", None),
            s3_endpoint_url=env("MANTHANA_SERVER_S3_ENDPOINT_URL", None),
            s3_access_key=env("MANTHANA_SERVER_S3_ACCESS_KEY", None),
            s3_secret_key=env("MANTHANA_SERVER_S3_SECRET_KEY", None),
            llm_provider=env("MANTHANA_SERVER_LLM", cls.llm_provider),
            llm_model=env("MANTHANA_SERVER_LLM_MODEL", cls.llm_model),
            llm_max_tokens=int(env("MANTHANA_SERVER_LLM_MAX_TOKENS", str(cls.llm_max_tokens))),
        )


__all__ = ["ServerConfig", "K_ANON_FLOOR_DEFAULT"]
