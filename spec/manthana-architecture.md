# Manthana — Realized Architecture (living doc)

*This document maps the spec to the actual code: concrete file paths, package
layout, schema field reference, and decisions made during the build. It is
updated every phase. Companion to `manthana.md` (vision), `manthana-decisions.md`
(locked decisions — wins on conflict), `manthana-action.md` (actions), and
`ECC_clone_instruction.md` (reuse).*

Last updated: 2026-06-19 — slice (§11) + server (§12,§13) + sync (§14,§15) + skill miner (§16,§17) + miner→server (§18) + dashboard control plane (§19).

---

## 1. Build scope & process (this engagement)

- **Scope:** Foundation + vertical slice (capture → store → compact → view →
  act), local side only. No server yet.
- **Process:** phase-by-phase, with review between phases.
- **Surfaces:** Claude Code first (built/tested against real transcripts); Codex
  as a registered stub until local sample data exists.
- **ECC reuse:** clone locally for reference; copy specific *literals* verbatim
  with per-literal attribution; re-express *patterns* in idiomatic Python; full
  attribution in `NOTICE` + `LICENSES/MIT-ECC.txt`. (ECC cloned to a sibling dir
  `../ecc-upstream`, outside the repo.)

## 2. Repository layout

```
manthana/                      (repo root; git, not yet pushed)
├── pyproject.toml             uv workspace root + ruff/pyright/pytest config
├── .python-version            3.12 (packages support >=3.11)
├── uv.lock                    committed lockfile
├── README.md  LICENSE  NOTICE
├── LICENSES/                  AGPL-3.0.txt · Apache-2.0.txt · MIT-ECC.txt
├── .github/workflows/ci.yml   lint + type-check + tests
├── schemas/                   dist: manthana-schemas      (Apache-2.0)
│   ├── pyproject.toml
│   ├── src/manthana/schemas/  Pydantic v2 models
│   └── json/                  generated JSON Schema mirror (committed)
├── collectors/                dist: manthana-collectors   (Apache-2.0)
│   └── src/manthana/collectors/base.py   Collector protocol + registry (seam)
├── agent/                     dist: manthana   + `manthana` CLI (Apache-2.0)
│   └── src/manthana/agent/    datahome.py · sync.py · cli.py
├── server/                    dist: manthana-server       (AGPL-3.0)
│   └── src/manthana/server/   skeleton (built in the server phase)
├── tests/                     test_personal_mode_invariant.py · test_schema_roundtrip.py
├── docs/                      (dev docs; see spec/ for architecture)
└── spec/                      specification + this doc
```

### Packaging decision: one namespace, four distributions

All four packages share the **PEP 420 implicit namespace** `manthana`
(`manthana.schemas`, `manthana.collectors`, `manthana.agent`,
`manthana.server`) — there is intentionally **no `src/manthana/__init__.py`** in
any package, so the namespace merges across separately-installed distributions.
This gives clean imports *and* keeps the AGPL server a distinct distribution from
the Apache client tooling. Build backend: `hatchling`, each with
`[tool.hatch.build.targets.wheel] packages = ["src/manthana"]`.

- `pip install manthana` → the local agent + `manthana` CLI (pulls
  `manthana-schemas`, `manthana-collectors`).
- `manthana-server` is installed separately by the org (AGPL boundary).

## 3. Language & tooling (locked)

Python 3.11+ (pinned 3.12 via `uv`); Pydantic v2; SQLModel (Phase 1);
FastAPI/asyncio (later); `typer` CLI; `uv`; `ruff`; `pyright`;
`pytest`+`pytest-asyncio`. CI runs `uv sync --all-packages` →
`ruff check` → `pyright` → `pytest`.

Quickstart: `uv sync --all-packages`, then `uv run {ruff check .,pyright,pytest}`.
Regenerate the JSON Schema mirror with `uv run manthana-schemas-export`.

## 4. Schema reference (`manthana.schemas`)

Source of truth = Pydantic models under `schemas/src/manthana/schemas/`,
mirrored to `schemas/json/*.schema.json` (CI-guarded by
`tests/test_schema_roundtrip.py`). All models are `extra="forbid"`.

| Entity | File | Origin |
|---|---|---|
| `Turn` | `turn.py` | decisions doc Turn fields + provenance extensions |
| `Session` | `session.py` | decisions doc Session fields + `resumed_from`, `source_path` |
| `FrictionPoint` | `friction.py` | decisions doc FrictionPoint shape |
| `BaseCompaction` | `compaction.py` | decisions doc BaseCompaction fields |
| `EngineeringCompaction` | `compaction.py` | decisions doc extension |
| `Action` | `action.py` | seam: action registry/catalog |
| `ActionAuditEntry` | `action.py` | seam: action audit log |
| `ActionQueueItem` | `action.py` | seam: server action queue |
| `ConsentEntry` | `consent.py` | seam: consent registry |
| enums | `enums.py` | `StrEnum`s for all controlled vocab |

**Documented extensions** (added beyond the decisions doc; logged here as the
user requested that nothing be left only in code):

- `Turn`: `seq` (order within session), `tool_use_id` (pair call↔result),
  `source_event_id`/`source_parent_id` (map back to raw transcript `uuid`/
  `parentUuid` for citations & cross-line tool pairing).
- `Session`: `ended_reason` (`SessionEndReason`), `source_path`.
- `BaseCompaction`: `id`, `kind` (discriminator), `prompt_version`,
  `schema_version`, `created_at`.

**Compaction polymorphism:** `BaseCompaction` (kind=`"base"`) ←
`EngineeringCompaction` (kind=`"engineering"`). Deserialize a mixed stream via
`CompactionAdapter` (a `TypeAdapter` over the `kind`-discriminated union). Sales/
Design deferred to v2; HR indefinitely.

### Turn flattening rules (transcript → Turns)

A raw Claude Code line may produce several Turns, ordered by `seq`:

- plain user text → `Turn(role=user, content=text)`
- assistant text block → `Turn(role=assistant, content=text)` (carries
  `model` + token usage)
- assistant `tool_use` block → `Turn(role=assistant, tool_name, tool_input,
  tool_use_id)`
- user `tool_result` block → `Turn(role=tool, tool_output, error, tool_use_id)`
  (paired to the call via `tool_use_id`)

Field map (verified against real `~/.claude/projects/<slug>/<sessionId>.jsonl`)
is documented at the top of `turn.py`.

## 4a. Local store (`manthana.agent.store`, Phase 1)

SQLite at `$MANTHANA_DATA_HOME/manthana.db` via SQLModel. Modules:
`tables.py` (table models), `migrations.py` (versioned migrations), `engine.py`
(engine + pragmas + optional sqlite-vec), `store.py` (`Store` CRUD/query API).

**Design decision — document-store-with-indexes** (logged per the standing
instruction): `manthana.schemas` stays pure Pydantic (DB-free, for the JSON
mirror and cross-language reuse). Each table carries typed **index columns**
(for `WHERE`/`ORDER BY`) plus an authoritative **`data` JSON column** holding the
full model dump; domain objects are reconstructed from `data` (so no field drifts
between contract and table). This re-expresses ECC's schema-validated
JSON-document store (`scripts/lib/state-store/`) and handles compaction
polymorphism trivially (`CompactionAdapter.validate_python(row.data)`). This is a
deliberate divergence from the decisions doc's literal "one SQLModel class for
validation + DB": validation lives in the contract package, persistence in the
store, joined by a round-trip test.

**Migrations** re-express ECC `migrations.js`: a `schema_migrations` table tracks
versions; pending migrations apply in order inside one transaction; idempotent.
Migration 1 builds tables from SQLModel metadata; later migrations may be raw SQL.

**Store API:** `Store.open(path|None)` / `Store.open_memory()`; sessions
(`upsert_session`, `get_session`, `list_sessions`, `set_session_mode`); turns
(`add_turns`, `get_turns`, `count_turns`); compactions (`upsert_compaction`,
`get_compaction`, `list_compactions`, `mark_released`). Sync (not async) for the
local agent; the server uses async later.

## 4b. Capture pipeline (Phase 2)

`manthana.collectors` (Apache-2.0) + `manthana.agent.capture`:

- **`ClaudeCodeCollector`** (`collectors/claude_code.py`): `discover()` globs
  `~/.claude/projects/*/*.jsonl` (excludes nested subagent files); `read(path)`
  parses JSONL → ordered `Turn`s + `FileMeta(cwd, git_branch, session_id, mtime)`.
  Parsing is fresh against the verified field map; flattening rules and once-per-
  line token attribution are documented at the top of the module. Robust line
  handling follows ECC `session-end.js`.
- **`sessionize`** (`collectors/sessionize.py`): surface-agnostic boundary
  inference — >30 min gap or >6 h cap split one transcript into multiple
  Sessions, chained by `resumed_from`; Stop-hook boundary is a live-daemon
  concern, not batch. Timestamps carry forward across meta lines.
- **`infer_project`** (`collectors/project.py`): `git rev-parse --show-toplevel`
  with cwd-basename fallback. **`resolve_actor`** (`collectors/identity.py`):
  `$MANTHANA_ACTOR` → global git email → OS user.
- **`CodexCollector`** (`collectors/codex.py`): registered stub (`parse` raises;
  no verified local format).
- **`manthana.agent.capture`**: `ingest_file` / `ingest_all` tie collector →
  `sessionize` → `Store`. New sessions default to Work mode (Phase 3 adds the
  toggle + redaction). Grounding: `ingest_all` over this machine's real data
  ingested 209 files → 425 sessions → 28,622 turns.

## 4c. Redaction + Work/Personal mode (Phase 3)

`manthana.agent.redaction` (+ `agent/config.py`, CLI):

- **`patterns.py`** copies the ECC `governance-capture.js` literals **verbatim**
  (SECRET_PATTERNS, APPROVAL_COMMANDS, SENSITIVE_PATHS), translated JS→Python
  with the JS source preserved in comments; **PII_PATTERNS** (email, phone) are
  Manthana additions. Attribution at the copy site + in `NOTICE`.
- **`Redactor`** (`redactor.py`): `detect`, `redact_text` (typed-overloaded),
  `redact_value` (recursive), `redact_turn`/`redact_turns` (return COPIES — the
  local store keeps full fidelity; redaction applies on the path to release / in
  the review preview), `detect_approval_required`, `detect_sensitive_path`.
  Optional `llm_scrub` hook (off by default; provider arrives Phase 4).
- **`config.py`**: optional `$MANTHANA_DATA_HOME/manthana.toml` (`[embeddings]`,
  `[redaction]`); `build_redactor()` bridges config → Redactor.
- **Work/Personal mode**: `Store.set_session_mode` + `manthana mode <id>
  work|personal`. Personal toggle flows straight into the sync gate
  (`eligible_for_sync`), tested end-to-end. New CLI: `capture`, `sessions`,
  `mode`.

## 4d. Compactor + cost (Phase 4)

- **`manthana.agent.llm`**: `LLMProvider` protocol; `ClaudeCLIProvider`
  (`claude -p --output-format json`, unwraps `.result`), `CodexCLIProvider`
  (`codex exec`), `MockProvider` (deterministic, for CI), `default_provider()`.
  No bundled key — uses the engineer's own access (decisions doc).
- **`manthana.agent.cost`**: `RATE_TABLE` copied verbatim from ECC
  `cost-tracker.js` + `get_rates`/`tier_of`; `estimate_cost(turns)` →
  `CostBreakdown` (token sums + USD), re-expressed from `sumUsageFromTranscript`
  but summing parsed Turn tokens.
- **`manthana.agent.compactor`**: v0 prompt (`prompt.py`) serializes turns and
  asks for a single JSON object; `Compactor.compact(session, turns)` parses
  defensively (`_extract_json` tolerates prose/fences; malformed → grounded
  fallback) and assembles an `EngineeringCompaction` — qualitative fields from
  the LLM, **deterministic fields (ids, duration, cost/tier) from Manthana's own
  data, never from the LLM**.
- **`manthana.agent.compact`**: `compact_session` / `compact_pending` (skips
  Personal-mode sessions). CLI: `manthana compact [session_id]`. The real
  `claude -p` path is intentionally not auto-run in tests (token spend); covered
  by MockProvider.

## 4e. Action dispatcher + dashboard (Phase 5)

- **Dispatcher seam** (`manthana.agent.actions`): `Dispatcher.dispatch(event)`
  routes `TriggerEvent`s to registered `ActionHandler`s, enforcing — in order —
  personal-mode exclusion (hard), consent opt-out, cooldown, and confidence
  threshold; every evaluation (fired/suppressed/failed) is written to the action
  audit log. `default_dispatcher(store)` registers the v1 handler; `tag_all`
  fires `session_closed` for all sessions.
- **Auto-tag action** (`actions/auto_tag.py`): the one live v1 action (engineer /
  write / silent). Writes `project`/`task_type`/`outcome`/`friction` tags to
  `Session.tags` (new documented field) on session close.
- **Store seams**: `action_audit` + `consent` tables (migration 2, idempotent
  `create_all`); `add_audit`/`list_audit`/`last_fired_at` (cooldown),
  `get_consent`/`set_consent`/`list_consent`, `update_session_tags`.
- **Dashboard** (`manthana.agent.dashboard`, FastAPI + HTMX, no build step):
  `/` sessions with one-click Work/Personal toggle + tags, `/cost` per-session +
  total, `/actions` audit log. CLI: `manthana dashboard`, `manthana retag`.

Vertical slice verified end-to-end: capture → store → compact → tag → view.

## 5. Trust contract in code

**The single sync chokepoint:** `manthana.agent.sync.eligible_for_sync`. ALL
data leaving the laptop must pass through it. Rules: personal-mode sessions never
sync (hard invariant), compactions upload only when `released=True`, unknown
session ⇒ fail closed. Enforced from commit one by
`tests/test_personal_mode_invariant.py` (passes before any sync transport
exists). Future ingestion/upload/action-dispatch code calls this gate; no bypass.

## 6. Action seams (present in v1, handlers land later)

- **Dispatcher** → `manthana.agent` (Phase 5).
- **`action_triggers`** field → on every compaction (present now).
- **Action queue** → `ActionQueueItem` (schema now; server table later).
- **Audit log** → `ActionAuditEntry` (schema now).
- **Consent registry** → `ConsentEntry` (schema now).

## 7. ECC reuse map → concrete Manthana paths

| ECC source | Manthana target | Mode | Status |
|---|---|---|---|
| `scripts/lib/agent-data-home.js` | `agent/.../agent/datahome.py` | re-express | ✅ done |
| `scripts/lib/session-adapters/*` | `collectors/.../collectors/base.py` | re-express | ✅ seam done |
| `schemas/state-store.schema.json` | `schemas/src/manthana/schemas/*` | extend | ✅ done |
| `scripts/lib/state-store/*` | local store (SQLite/PG) | re-express | Phase 1 |
| `scripts/hooks/session-end.js` `extractSessionSummary` | collector parse | re-express | Phase 2 |
| `scripts/hooks/governance-capture.js` `SECRET_PATTERNS`/`APPROVAL_COMMANDS`/`SENSITIVE_PATHS` | redaction module | **copy verbatim** | Phase 3 |
| `scripts/hooks/cost-tracker.js` `RATE_TABLE` + summation | cost module | **copy verbatim** + re-express | Phase 4 |
| `scripts/lib/skill-evolution/{tracker,provenance,versioning}.js` | skill miner | re-express | (post-slice) |

Attribution: re-expressed files carry a header comment crediting the ECC source;
verbatim literals get a per-literal comment at the copy site; `NOTICE` tracks all
of it (entries marked `[lands in Phase N]` for not-yet-written imports).

## 8. Tenancy model (locked, built in the server phase)

**Org > Team > Actor**, with **Project** as a cross-cutting tag. `actor` is the
engineer identity (org email, e.g. `name@org.com`). The local agent authenticates
to the server with a team-scoped token (JWT). k-anonymity floor: no team-level
aggregate with <4 distinct released-compaction contributors.

## 9. Open / tracked items

- **Server-side `LLMProvider`** for founder-narrative generation: the server has
  no engineer Claude account. Dev = mock provider; **v1.5 = org provisions a
  server API key**. Tracked here and in `manthana-decisions.md`.
- **Codex format:** spec's `~/.codex/sessions/` path is stale on current Codex
  (SQLite-based, no JSONL on this machine). Codex collector is a registered stub
  until sample data exists.
- **Python 3.14 wheels:** project pinned to 3.12 because heavy deps
  (torch/sentence-transformers, Phase: skill miner) may lack 3.14 wheels;
  embeddings will be an optional extra so the core installs without them.

## 10. Phase status

- ✅ **Phase 0 — Foundation**: monorepo, schemas + JSON mirror, attribution,
  personal-mode invariant, CI. Green.
- ✅ **Phase 1 — Local SQLite store** (§4a): SQLModel tables, versioned
  migrations, `Store` CRUD, sqlite-vec wired optional. Green (15 tests).
- ✅ **Phase 2 — Claude Code collector** (§4b): JSONL parse + flatten,
  sessionization, project/actor inference, capture pipeline, Codex stub.
  Green (22 tests); verified on real data.
- ✅ **Phase 3 — Redaction + Work/Personal mode** (§4c): verbatim ECC secret
  patterns + PII, Redactor (copies), config, mode toggle wired to the sync gate,
  CLI (capture/sessions/mode). Green (29 tests).
- ✅ **Phase 4 — Compactor + cost** (§4d): LLM provider abstraction (Claude/Codex
  CLI + Mock), verbatim ECC RATE_TABLE + cost estimation, v0 prompt, defensive
  compactor → EngineeringCompaction. Green (37 tests).
- ✅ **Phase 5 — Dashboard + auto-tag + dispatcher** (§4e): action dispatcher
  seam (consent/cooldown/audit/personal-exclusion), auto-tag action, FastAPI+HTMX
  dashboard. Green (47 tests). **Vertical slice complete.**

**Next scope (not in this engagement):** server (FastAPI ingestion, Postgres +
pgvector, multi-tenancy, k-anonymity, founder query), the remaining 7 v1 actions,
skill miner v0, daemon packaging.

## 11. Adversarial review hardening (2026-06-19)

A multi-agent adversarial review (4 reviewers → skeptical triage) surfaced 11
confirmed issues across the slice; all fixed with regression tests in
`tests/test_review_fixes.py`:

- **[high] Dispatcher fail-closed** — an unresolvable session (None/unknown id)
  no longer reaches a handler; suppressed as `session_unresolved`, mirroring the
  sync gate.
- **[high] Sessionize boundary** — `seg_start` now late-initializes on the first
  real timestamp, so gap/cap splits fire even when a segment opens with
  timestamp-less turns.
- **[high] Idempotent re-ingest** — `Store.delete_session_family` clears a
  transcript's session family before re-persist (no phantom `S.2` / stale
  `turn_count`); verified on real data (425 sessions stable across re-ingest).
- **[med] UTC ordering** — index columns store UTC ISO (`_utc_iso`) so lexical
  `ORDER BY` is chronological across mixed offsets (fixes `list_*` /
  `last_fired_at`/cooldown ordering).
- **[med] Robust JSON extraction** — compactor `_extract_json` scans braces with
  `raw_decode`, surviving prose/fences with stray braces.
- **[low] Cost tier consistency** — `resolve_tier` returns the applied pricing
  tier (sonnet for unknown-but-present models), so `tier` agrees with `usd`.
- **[low] `_str_list` excludes bool** (bool is an int subclass).
- **[low] Migration honesty** — migration 2 creates exactly the action/consent
  tables via a dedicated function.
- **[low] Attribution roll-up** — `NOTICE` reflects shipped derivations (no
  "[lands]" markers) and includes `engine.py` (pragmas) and `claude_code.py`
  (session-end.js line-handling); `engine.py` cites its exact ECC path.

## 12. Org server + founder query (`manthana.server`, AGPL-3.0)

The org-side, self-hosted server. SQLite for dev/tests, Postgres for prod (same
SQLModel models); pgvector is reserved for the later skill miner, not needed by
the founder query.

**Modules** (`server/src/manthana/server/`):

- `config.py` — `ServerConfig` from `MANTHANA_SERVER_*` env (DB URL, JWT secret,
  admin token, k-anon floor, object store). Insecure dev defaults; override in prod.
- `tables.py` — multi-tenant SQLModel tables (distinct names to avoid clashing
  with the local store on shared metadata): `org`, `team`, `actor`,
  `released_compaction`, `raw_transcript`, `action_queue` (seam), `org_consent`
  (seam). Same index-columns + `data` JSON pattern; UTC-normalized timestamps.
- `db.py` — engine (SQLite/Postgres, StaticPool for `:memory:`) + `init_db`.
- `auth.py` — **JWT team-scoped tokens** (`issue_team_token`/`verify_team_token`,
  claims = actor/org/team) for agents; a static **admin token** for admin +
  founder endpoints.
- `store.py` — `ServerStore`: tenancy CRUD, `ingest_compaction` (org/team from
  token, upserts actor), `query_compactions` (org-scoped + filters), `record_raw`,
  consent.
- `storage.py` — `ObjectStore` (`InMemoryObjectStore` for dev/tests;
  `S3ObjectStore`/boto3 for prod — MinIO/S3/GCS/R2) for raw-transcript release.
- `llm.py` — server-side `LLMProvider` (`MockProvider`/`ScriptedProvider`); kept
  separate from the agent's so the AGPL server stays decoupled. **Open item:**
  dev = mock; v1.5 the org provisions a real server key behind this interface.
- `founder.py` — **structured-filter-first** pipeline: NL → LLM-parsed
  `FounderFilter` → org-scoped SQL → **k-anonymity floor** (distinct contributors
  < `k_anon_floor` ⇒ `insufficient data`, rollup suppressed) → grounded narrative
  whose claims cite compaction ids; **non-optional grounding** (a narrative citing
  nothing is withheld, rollup still returned).
- `app.py` — FastAPI: `/healthz`, `/v1/admin/{orgs,teams,tokens}` (admin),
  `/v1/compactions` + `/v1/compactions/{id}/raw` (team JWT), `/v1/founder/query`
  (admin). Uses inline `Annotated[..., Depends(...)]` (no `from __future__ import
  annotations` here, so FastAPI resolves closure-scoped deps at runtime).
- `cli.py` — `manthana-server {serve,create-org,create-team,token}`.

**Auth model:** admin bootstraps orgs/teams and mints team tokens; the local
agent authenticates with its team JWT to ingest; the founder uses the admin token
to query. **Dev infra:** `docker-compose.yml` (Postgres+pgvector, MinIO).

**Tenancy:** Org > Team > Actor; Project = tag. Every server row is org-scoped;
the founder query is always org-scoped. Tests: `tests/test_server.py` (auth,
ingestion, raw release, k-anon suppression, grounded vs ungrounded narrative) on
SQLite + in-memory object store + scripted provider.

### Phase status (updated)

- ✅ **Phase 6 — Server core**: tenancy, JWT auth, ServerStore, ingestion, raw
  release, k-anonymity, object store, docker-compose. 
- ✅ **Phase 7 — Founder query**: parse → SQL → k-anon → grounded narrative with
  citations + insufficient-data fallback. Green (64 tests total).

**Still next:** remaining 6 v1.5 actions, skill miner v0 (pgvector), daemon
packaging, agent→server sync transport (the agent's `eligible_for_sync` →
`/v1/compactions`).

## 13. Server adversarial review hardening (2026-06-19)

A 3-reviewer adversarial pass over the server surfaced 11 confirmed issues; all
fixed with regression tests in `tests/test_server_fixes.py`:

- **[high] Cross-tenant compaction isolation** — released-compaction PKs are now
  org-namespaced (`org::id`), so one org's compaction id can never overwrite or
  re-tag another's; reads are org-scoped.
- **[high] Cross-tenant raw upload** — `POST /v1/compactions/{id}/raw` now uses
  `get_owned_compaction` (org+team scoped) and 404s (not 403) cross-tenant.
- **[high] Fail-closed on release** — the server rejects unreleased compactions
  at ingest (`NotReleasedError`/422) AND only ever stores/returns
  `released=True` rows (new `released` index column + query filter).
- **[high] Raw upload requires release** — covered by the owned+released lookup.
- **[high] Date-range off-by-a-day** — `until` (date-only) is treated as a
  half-open upper bound so the whole boundary day is included; `since` expands to
  `T00:00:00+00:00`.
- **[med] Per-bucket k-anonymity** — `by_project`/`by_outcome` sub-aggregates
  backed by < floor contributors are suppressed (not just the global count), and
  the narrative only sees surviving cohorts.
- **[med] Atomic batch ingest** — the whole batch is validated (and
  release-checked) before any row is persisted.
- **[med] JWT requires `exp`** + the org/team/sub claims at decode (rejects
  forged/non-expiring tokens).
- **[med] Filter validation** — invalid `outcome`/`surface` values are nulled
  (no spurious empty results); `cursor` added to the parse prompt.
- **[med] Constant-time admin token** comparison (`hmac.compare_digest`).
- **[low] Robust citations** — regex `[id]` extraction instead of substring scan.

## 14. Agent → server sync transport (`manthana.agent.sync_client`)

Closes the loop end-to-end. `SyncClient.sync(store)`:

1. reads sync-eligible compactions via `eligible_for_sync` (the single egress
   chokepoint — personal-mode excluded, released-only, fail-closed);
2. skips ids already in the local `sync_state` table (idempotent / incremental);
3. **redacts** each compaction's free text (`Redactor.redact_compaction`) —
   redaction-on-release, so secrets/PII never cross the boundary (the local store
   keeps full fidelity);
4. POSTs the batch to `POST /v1/compactions` with the team JWT;
5. optionally releases raw transcripts (redacted turns as JSONL) to
   `POST /v1/compactions/{id}/raw` (`--raw`);
6. records `mark_synced` for each pushed compaction.

CLI: `manthana sync [--raw]` (server URL + team token from
`MANTHANA_SERVER_URL`/`MANTHANA_TEAM_TOKEN` or `[server]` in `manthana.toml`).
Local store gains a `sync_state` table (migration 3) + `mark_synced`/`synced_ids`.

**Verified end-to-end** (`tests/test_sync.py` + capstone run): capture → compact
→ release → sync → ingest → founder query returns a grounded, cited narrative;
personal/unreleased compactions never sync; re-sync is idempotent; secrets are
redacted before egress.

### Phase status

- ✅ **Phase 8 — Agent→server sync**: SyncClient (eligible→redact→POST), raw
  release, idempotent sync-state, `manthana sync` CLI. 75 tests green.

**The v1 trust loop is now complete.** Still next: remaining v1.5 actions, skill
miner v0 (pgvector), daemon packaging, server-side real LLM provider (v1.5).

## 15. Sync egress review hardening (2026-06-19)

A 2-reviewer pass over the egress path confirmed 5 issues (the eligibility gate
itself had no bypass); all fixed with regression tests:

- **[high] Redaction completeness (compaction)** — `redact_compaction` now
  default-redacts every str / list[str] field except a structural keep-set, so
  EngineeringCompaction fields (`files_touched`, `prs_opened`, …) are scrubbed,
  not just `task_intent`/`approach`/`artifacts`.
- **[high] Redaction completeness (turn)** — `redact_turn` now also scrubs
  `error` (stack traces can echo secrets) and **dict keys** in `tool_input`.
- **[high] Raw-upload sync-state** — metadata is `mark_synced` immediately after a
  verified push (before raw); raw upload is isolated (per-item try/except) and
  tracked separately (`raw_synced_at`), so a raw failure retries instead of being
  lost or forcing a metadata re-push.
- **[med] Verified ingest** — the client checks the server's `ingested` count
  (raises `SyncError` on mismatch, so nothing is marked synced) and guards a
  malformed 200 body.

## 16. Skill miner v0 (`manthana.agent.skillminer`)

Built against a fact-checked deep-research pass (108 agents; sources: Anthropic
Agent Skills docs/engineering blog, sentence-transformers, scikit-learn, UMAP,
peer-reviewed short-text clustering). Pipeline: embed → cluster (+ recurrence /
k-anon gate) → synthesize → validate/render SKILL.md → provenance + content hash.

**Modules:**
- `embed.py` — `Embedder` protocol; `HashingEmbedder` (deterministic, dep-free,
  default for tests/offline); `SentenceTransformerEmbedder` (bge-large via the
  optional `embeddings` extra); `default_embedder()` prefers ST, falls back to
  hashing; cosine on L2-normalized vectors.
- `cluster.py` — SBERT-style **community detection** (greedy, non-overlapping,
  unknown-k; cosine `threshold` 0.75 + min cluster size). **k-means avoided**
  (fixed k). The **≥N-contributor/session recurrence gate is applied post-hoc**
  on cluster membership (`recurring(...)`) — correct for k-anonymity (10 sessions
  from one person don't qualify).
- `skillmd.py` — the verified Anthropic format: `name` (≤64, `^[a-z0-9-]+$`, no
  `anthropic`/`claude`) + `description` (non-empty, ≤1024, no XML tags) required;
  validation, slug/repair, and rendering. Description is the load-bearing trigger
  artifact (third person, what + when).
- `synthesize.py` — LLM synthesis (give the model ALL cluster members; extract the
  common invariant, don't overfit) with validate/repair; **deterministic fallback**
  so mining works offline/in tests and never crashes.
- `provenance.py` — re-expressed from ECC `skill-evolution/provenance.js`: a
  validated record (source/created_at/confidence) + Manthana evidence trail
  (compaction ids), contributor/session counts, cohesion, and **content-hash**
  versioning (`sha256:`, from ECC `skillVersion.contentHash`). Written as a
  `provenance.json` sidecar so SKILL.md frontmatter stays portable.
  Privacy: contributor names included only for personal mining;
  `include_contributors=False` for org-level k-anon (count only).
- `miner.py` — `SkillMiner.mine(...)` orchestrates; `write_proposal` writes
  `<dir>/<name>/{SKILL.md,provenance.json}`; `mine_personal(store)` mines the
  engineer's own compactions (gate = ≥3 distinct sessions). CLI:
  `manthana mine-skills [--write]` (deterministic by default — no token spend).

**Researched gaps (logged):** no authoritative sources survived for synthesis
prompts, provenance/versioning schemes, or exact k-anon thresholds — those use
sound defaults + the ECC framework + the spec's locked ≥3 (personal) / ≥4 (org)
floors. The specific embedding model (bge-large), L2/cosine, and a dedup cutoff
are decisions-doc choices, not independently verified; validate on real corpus.

### Phase status

- ✅ **Phase 9 — Skill miner v0**: embed/cluster/synthesize/validate/provenance,
  CLI, optional bge-large extra. Green (91 tests). Org-level cross-engineer mining
  (pgvector, ≥4-contributor k-anon) reuses this core — deferred to the v1.5 action.

## 17. Skill miner review hardening (2026-06-19)

A 2-reviewer adversarial pass confirmed 10 issues (all real); fixed with
regressions in `tests/test_skillminer.py`:

- **[high] Embedder bug** — `HashingEmbedder` collapsed each token to its first
  byte (cosine 1.0 for unrelated texts, breaking the default offline clustering);
  now hashes the whole token (blake2b).
- **[high] Invalid SKILL.md** — control chars in a description (NUL/BEL/CR…) broke
  YAML; now stripped + rejected by `validate_description`.
- **[high] Reserved-word slug** — `slugify_name` could re-form `anthropic`; now
  removes reserved words to a fixpoint and `repair_draft` hard-falls-back to a
  guaranteed-valid name.
- **[high] Null-field garbage** — `str(None)` produced a kept "none" skill; a
  type-checked coercion now forces the deterministic fallback.
- **[med] Content redaction** — the miner now redacts compaction free text
  (`Redactor.redact_compaction`) BEFORE it reaches embeddings, the synthesis
  prompt, or the skill body, so secrets/PII never enter a mined skill.
- **[med] k-anon entry point** — `mine()` forbids `include_contributors=True`
  with `min_contributors>1`; `mine_org()` hardcodes the ≥`K_ANON_FLOOR`(=4)
  contributor floor + drops names.
- **[med] JSON extraction** — prefers the real answer (last dict / the one with a
  `description`) over a prose example, after stripping ```json fences.
- **[med] Write collisions** — `write_proposal` suffixes (`name-2`…) instead of
  clobbering, idempotent on identical content.
- **[low] O(n²) cap** — clustering caps to the most-recent `max_items` (2000) so a
  large store can't OOM.
- **[low] Provenance validation** — now also checks non-negative counts,
  non-empty evidence, `sha256:` hash, and contributor count↔names consistency.

## 18. Skill miner extracted to a shared package + wired into the server

To use the miner from the AGPL server without dragging in the local agent
(dashboard/collectors), the skill miner was extracted to its own Apache-2.0
workspace package **`manthana-skills`** (`skills/`, import `manthana.skills`),
depended on by both `agent` and `server`.

- **Decoupling:** the miner's provider + redactor are now injected via local
  Protocols (`manthana.skills.provider.LLMProvider` / `SupportsRedaction`) — no
  import of agent or server internals. `SkillMiner(redactor=None)` by default.
- **Agent** (`manthana.agent.skillminer`, thin shim): `mine_personal(store)` wires
  the agent's `Redactor` + local store; `manthana mine-skills` unchanged.
- **Server**: `POST /v1/admin/mine-skills {org_id}` (admin) runs `mine_org` over
  the org's released compactions (already redacted on sync, so `redactor=None`),
  **k-anonymized** (≥`K_ANON_FLOOR`=4 distinct contributors, names dropped),
  using the server's own LLM provider; each proposal is **enqueued in the action
  queue** (`ServerStore.enqueue_action`, status `pending`) for human approval —
  the v1.5 "auto-draft shared org skills" action, with the maintainer-approval
  gate as a seam. Verified end-to-end (5 contributors → 1 queued org skill).

### Phase status

- ✅ **Phase 10 — Miner→server**: `manthana-skills` shared package; org mining
  endpoint behind k-anon + action queue. Green (104 tests).

## 19. Dashboard control plane (Phase 11)

The local dashboard (`manthana.agent.dashboard.app`) is now read **and** act —
the employee runs the whole flow from the browser, no terminal needed:

- **Pages:** Sessions, **Compactions** (review-before-sync inbox), **Skills**
  (mined SKILL.md viewer reading `~/.claude/skills/personal/`), Cost, Actions.
- **Actions (POST → 303 redirect; tunables via query string, so no
  python-multipart):** `/capture` (ingest_all), `/session/{id}/compact`
  (compact_session — labelled "runs claude, costs tokens"), `/compaction/{id}/release`
  (toggle), `/skills/mine?threshold=…` (mine_personal + write_proposal), `/sync`
  (SyncClient if configured, else an in-page notice). Work/Personal stays htmx.
- **Testability:** `create_app(store, *, provider=None, skills_dir=None)` — tests
  inject a `MockProvider` (no claude) + a tmp skills dir + monkeypatch capture, so
  the suite is hermetic. CLI `manthana dashboard` uses the defaults.
- All rendered values go through `html.escape`; path params hit parameterized
  store lookups; localhost, single-employee, no auth by design.

Reuses (not reinvented): `capture.ingest_all`, `compact.compact_session`,
`skillminer.{mine_personal,write_proposal}`, `sync_client.SyncClient`,
`store.*`, `cost.estimate_cost`. Green (107 tests); verified live on real data.

## 20. Founder web console (`manthana.server.ui`)

The org side now has a browser GUI beyond Swagger `/docs`
(`mount_ui(app, config, store, provider)`, mounted by `create_app`):

- **Auth — cookie login.** Org-wide data ⇒ gated (unlike the localhost employee
  dashboard). `POST /ui/login` checks the admin token with
  `hmac.compare_digest` (constant-time, same gate as `X-Admin-Token`) and sets an
  **httponly** `manthana_admin` cookie; every `/ui*` route re-checks it and
  **303-redirects unauthenticated callers to `/ui/login`, leaking no org data**.
  The token rides in a POST form body, never a URL (needs `python-multipart`;
  added as a server dep). `GET /ui/logout` clears the cookie.
- **Pages / actions:** `GET /ui` console — founder-query form (org dropdown +
  question) + a per-org table (teams, released-compaction count, pending-skill
  queue) + a **Mine org skills** button. `POST /ui/query` → `founder.run_query`
  → renders the rollup + grounded narrative + citations (or "insufficient data"
  when k-anon/grounding fails — no hallucinated answer). `POST /ui/mine` →
  `skills.mine_org` (hardcoded k-anon floor 4, names dropped) → `enqueue_action`
  for each proposal → back to the console for approval.
- **Reuse:** `founder.run_query`, `skills.mine_org`, `store.{list_orgs,list_teams,
  count_compactions,query_compactions,enqueue_action,list_queue}`. Like `app.py`,
  this module omits `from __future__ import annotations` so FastAPI can resolve
  `Form`/`Cookie` on the closure-scoped routes at runtime. All values
  `html.escape`d.
- **Testability:** `tests/test_server_ui.py` (8 tests) on in-memory SQLite + a
  `MockProvider` — covers the auth gate (unauth → redirect, no data), wrong-token
  401, console listing, query rollup/citation, below-k-anon "insufficient", mine
  enqueue, and logout. **115 tests green**; verified live against Postgres (5433):
  gate → login → console (real `actioneer` org, 4 compactions) → query (real
  rollup `{scribe: 4}`, narrative withheld since the dev server LLM is mock) →
  mine (suppressed at 1 contributor) → logout.

> Run the Postgres-backed server with the driver extra installed:
> `uv pip install "psycopg[binary]"` (or `uv sync` the `manthana-server[postgres]`
> extra) — a plain `uv sync --all-packages` does **not** pull optional extras.

## 21. Non-blocking compaction (dashboard)

The dashboard's **Compact** button used to block the request for the whole
~30-60s `claude` call. It now runs off the request thread:

- `POST /session/{id}/compact` adds the id to an in-progress `set[str]` (guarded
  by a `threading.Lock` held in the `create_app` closure), starts a **daemon
  thread** running `compact_session`, and 303-redirects to `/` immediately. The
  worker `discard`s the id in a `finally`. A second click while a session is
  already compacting is a no-op (the lock-checked guard won't re-spawn).
- The Sessions page renders **⏳ compacting…** for in-progress ids and **✓
  compacted** once done, and emits `<meta http-equiv="refresh" content="4">`
  **only while** something is in flight (it stops polling when idle).
- **Cross-thread SQLite:** `store/engine.py` now opens the **file** engine with
  `check_same_thread=False` (the in-memory engine already did) plus
  `PRAGMA busy_timeout=5000`, so the worker thread's writes and the request
  thread's reads coexist safely (WAL + short transactions, single user).
- **Tests** (`tests/test_dashboard.py`): a gated provider makes the in-progress
  state deterministic — async-completes, shows "compacting…" then "✓ compacted",
  and a double-click does not start a second compaction. **117 tests green.**

## 22. Adversarial review hardening — founder UI + async compaction (2026-06-19)

A review workflow (4 dimensions → per-finding adversarial verify → completeness
critic; 21 agents, 16 raw → 10 confirmed) ran over `ui.py`, `dashboard/app.py`,
`server/store.py`, `engine.py`. Fixes applied (119 tests; verified live):

- **Silent daemon-thread failure** (dashboard async compaction): `_run_compaction`
  now `except Exception: _log.exception(...)` before the `finally` discard, so a
  failed background compaction is logged instead of vanishing. Regression test
  drives a raising provider and asserts the log + clean in-progress teardown.
  (The flagged "TOCTOU double-write" was downgraded — the id is removed only
  *after* `compact_session` returns/raises, so there is no concurrent double-write;
  a re-click after a *failure* is intended retry.)
- **Empty-secret auth bypass** (`config.py`): `hmac.compare_digest("", "")` is
  `True`, so an empty `admin_token`/`jwt_secret` would authenticate. `ServerConfig.
  __post_init__` now rejects empty values (dev defaults are non-empty).
- **`count_compactions`** now filters `released == True`, matching
  `query_compactions` (consistent counts even if an unreleased row ever lands).
- **Logout is POST** (was GET) — state mutation must not be GET-triggerable; the
  nav uses a form button. Verified live: `GET /ui/logout` → 405, `POST` → 303.
- **Cookie scoping**: `set_cookie`/`delete_cookie` use `path="/ui"` + httponly.
- **`<title>` escaping** in both `_page`s (`_e(title)`) — defense-in-depth (titles
  are literals today).
- **Tracked, not changed:** the critic flagged per-filter k-anon enumeration in
  the *pre-existing* `founder.py`. Current code already suppresses per-project /
  per-outcome sub-buckets below the floor and collapses an `actor` filter to one
  contributor → "insufficient". Logged in `manthana-decisions.md` as a v1.5
  hardening (per-filter contributor floor) rather than touched in this pass.

### Phase status

- ✅ **Phase 11 — Dashboard control plane**: compactions + skills pages + action
  buttons. The dashboard is now the employee's full GUI.
