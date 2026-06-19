"""FastAPI application: admin bootstrap, ingestion, raw release, founder query.

Auth: agent endpoints require a team-scoped JWT (Authorization: Bearer …); admin
and founder endpoints require the configured admin token (X-Admin-Token). Sync
endpoints run in FastAPI's threadpool over the sync ServerStore (the decisions
doc's async note is satisfied at the FastAPI layer; the DB layer mirrors the
local store for testability — can move to asyncpg later).

NOTE: this module intentionally does NOT use ``from __future__ import
annotations`` — FastAPI must resolve the ``Depends``/``Header`` dependencies in
the route annotations at runtime, which stringized annotations would break for
the closure-scoped dependency functions. Inline ``Annotated[...]`` keeps it
pyright-clean and avoids ruff B008 (no function call in a default value).

SPDX-License-Identifier: AGPL-3.0-or-later
"""

import hmac
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from manthana.schemas import CompactionAdapter
from manthana.skills import mine_org
from pydantic import BaseModel, ValidationError

from .auth import AuthError, TeamClaims, issue_team_token, verify_team_token
from .config import ServerConfig
from .founder import run_query
from .llm import LLMProvider, MockProvider
from .storage import ObjectStore, make_object_store
from .store import ServerStore
from .ui import mount_ui


class CreateOrg(BaseModel):
    org_id: str
    name: str


class CreateTeam(BaseModel):
    team_id: str
    org_id: str
    name: str


class MintToken(BaseModel):
    org_id: str
    team_id: str
    actor: str


class IngestBody(BaseModel):
    compactions: list[dict[str, Any]]


class RawBody(BaseModel):
    content: str


class FounderQueryBody(BaseModel):
    org_id: str
    query: str


class MineSkillsBody(BaseModel):
    org_id: str


def create_app(
    config: ServerConfig,
    store: ServerStore,
    object_store: ObjectStore,
    provider: LLMProvider,
) -> FastAPI:
    app = FastAPI(title="Manthana Server")

    def require_admin(x_admin_token: Annotated[str, Header()] = "") -> None:
        # constant-time comparison — admin token gates org/team/token mint + founder query
        if not hmac.compare_digest(x_admin_token, config.admin_token):
            raise HTTPException(status_code=401, detail="invalid admin token")

    def require_team(authorization: Annotated[str, Header()] = "") -> TeamClaims:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            return verify_team_token(config.jwt_secret, authorization.removeprefix("Bearer "))
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/admin/orgs")
    def create_org(body: CreateOrg, _: Annotated[None, Depends(require_admin)]) -> dict[str, str]:
        store.create_org(body.org_id, body.name)
        return {"created": body.org_id}

    @app.post("/v1/admin/teams")
    def create_team(body: CreateTeam, _: Annotated[None, Depends(require_admin)]) -> dict[str, str]:
        store.create_team(body.team_id, body.org_id, body.name)
        return {"created": body.team_id}

    @app.post("/v1/admin/tokens")
    def mint_token(body: MintToken, _: Annotated[None, Depends(require_admin)]) -> dict[str, str]:
        token = issue_team_token(
            config.jwt_secret, org_id=body.org_id, team_id=body.team_id, actor=body.actor
        )
        return {"token": token}

    @app.post("/v1/compactions")
    def ingest(
        body: IngestBody, claims: Annotated[TeamClaims, Depends(require_team)]
    ) -> dict[str, int]:
        # Validate (and require released) the WHOLE batch before persisting any,
        # so a bad item never leaves a partial commit.
        compactions = []
        for raw in body.compactions:
            try:
                compaction = CompactionAdapter.validate_python(raw)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=f"invalid compaction: {exc}") from exc
            if not compaction.released:
                raise HTTPException(
                    status_code=422, detail=f"compaction {compaction.id} is not released"
                )
            compactions.append(compaction)
        for compaction in compactions:
            store.ingest_compaction(compaction, org_id=claims.org_id, team_id=claims.team_id)
        return {"ingested": len(compactions)}

    @app.post("/v1/compactions/{compaction_id}/raw")
    def upload_raw(
        compaction_id: str, body: RawBody, claims: Annotated[TeamClaims, Depends(require_team)]
    ) -> dict[str, str]:
        # Tenant-scoped + released-only lookup; 404 (not 403) so cross-tenant
        # existence is not disclosed.
        if store.get_owned_compaction(compaction_id, claims.org_id, claims.team_id) is None:
            raise HTTPException(status_code=404, detail="unknown compaction")
        key = f"{claims.org_id}/{claims.team_id}/{compaction_id}.jsonl"
        object_store.put(key, body.content.encode("utf-8"))
        store.record_raw(compaction_id, claims.org_id, key)
        return {"object_key": key}

    @app.post("/v1/founder/query")
    def founder_query(
        body: FounderQueryBody, _: Annotated[None, Depends(require_admin)]
    ) -> dict[str, Any]:
        result = run_query(store, config, org_id=body.org_id, query=body.query, provider=provider)
        return {
            "filter": result.filter.model_dump(),
            "rollup": result.rollup.__dict__ if result.rollup else None,
            "narrative": result.narrative,
            "citations": result.citations,
            "insufficient_data": result.insufficient_data,
        }

    @app.post("/v1/admin/mine-skills")
    def mine_skills(
        body: MineSkillsBody, _: Annotated[None, Depends(require_admin)]
    ) -> dict[str, Any]:
        # Cross-engineer org mining over released compactions. k-anonymized
        # (>=K_ANON_FLOOR distinct contributors; names dropped). Compactions are
        # already redacted on sync, so no redactor is needed here. Proposals are
        # enqueued for human approval (the action-queue seam) rather than applied.
        compactions = store.query_compactions(org_id=body.org_id, limit=100_000)
        proposals = mine_org(compactions, provider=provider)
        out = []
        for proposal in proposals:
            store.enqueue_action(
                action_id="auto_draft_org_skill",
                org_id=body.org_id,
                payload={
                    "name": proposal.draft.name,
                    "description": proposal.draft.description,
                    "skill_md": proposal.skill_md,
                    "contributor_count": proposal.provenance.contributor_count,
                    "evidence": proposal.provenance.evidence,
                },
            )
            out.append(
                {
                    "name": proposal.draft.name,
                    "description": proposal.draft.description,
                    "contributor_count": proposal.provenance.contributor_count,
                    "evidence": proposal.provenance.evidence,
                }
            )
        return {"proposals": out, "queued": len(out)}

    mount_ui(app, config, store, provider)
    return app


def build_default_app() -> FastAPI:
    """App wired from environment config (uvicorn entry point)."""
    config = ServerConfig.from_env()
    store = ServerStore.open(config.db_url)
    object_store = make_object_store(config)
    # v1.5: org provisions a real server-side provider; dev returns "{}".
    provider: LLMProvider = MockProvider("{}")
    return create_app(config, store, object_store, provider)


__all__ = ["create_app", "build_default_app"]
