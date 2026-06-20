# Trust, Privacy and Security Model

The trust contract in depth: the employee owns the local store; the org sees only released, redacted, and k-anonymized data; personal-mode sessions never leave the laptop.

---

## 1. The Trust Contract

Manthana is built around a strict trust contract enforced at the code level:

- **Employee ownership:** The engineer owns their local store (`$MANTHANA_DATA_HOME/manthana.db`) and every transcript captured from their work. This is the source of truth and is never synchronized without explicit action.
- **Org visibility boundary:** The org sees **only** data the engineer has:
  1. Explicitly **released** (toggled in the dashboard or via CLI before sync),
  2. **Redacted** on the path to the server (secrets, PII, sensitive file paths removed), and
  3. **k-anonymized** at the org level (no aggregate report on fewer than 4 distinct contributors per query filter).
- **Personal-mode hard invariant:** Sessions marked as "Personal" never sync, never trigger actions, and never reach any team report — not even if explicitly released. This is enforced by a dedicated test (`tests/test_personal_mode_invariant.py`) that has existed from commit one.

The **single point of truth** is the function `manthana.agent.sync.eligible_for_sync`. Every byte of data that leaves the laptop passes through this gate; there is no bypass.

---

## 2. The Sync Chokepoint: `eligible_for_sync`

Located in `agent/src/manthana/agent/sync.py`, this function implements the three rules:

```python
def eligible_for_sync(
    compactions: Iterable[BaseCompaction],
    sessions_by_id: Mapping[str, Session],
) -> list[BaseCompaction]:
    """Return only the compactions cleared to leave the laptop.

    Rules (v1):
      1. The owning session must NOT be personal mode (hard invariant).
      2. The compaction must be explicitly released (``released=True``).
      3. An unknown owning session fails closed (excluded).
    """
```

**Rule 1 — Personal-mode block (hard invariant):**
```python
if not session_is_syncable(session):
    continue  # personal-mode invariant
```
A session in `Mode.personal` will never be syncable, regardless of the `released` flag. There is no override, carve-out, or consent mechanism for this rule.

**Rule 2 — Explicit release gate:**
```python
if not compaction.released:
    continue  # compactions upload only on explicit release
```
Before a compaction can sync, the engineer must toggle its `released` flag to `True` in the dashboard's Compactions page (or via `manthana release <compaction_id>`). This is a review-before-sync pattern — the employee sees the compaction content (with redactions applied in preview) before committing to release.

**Rule 3 — Fail-closed on unknown session:**
```python
session = sessions_by_id.get(compaction.session_id)
if session is None:
    continue  # fail closed: never sync something we can't classify
```
If the owning session cannot be found (corrupt reference, data loss), the compaction is excluded rather than uploaded. This prevents accidental leaks of orphaned data.

### The Invariant Test

The personal-mode invariant is enforced by `tests/test_personal_mode_invariant.py`, which must pass before any sync code is merged:

```python
def test_personal_compaction_never_syncs_even_when_released() -> None:
    sessions = {
        "work": _session("work", Mode.work),
        "personal": _session("personal", Mode.personal),
    }
    compactions = [
        _compaction("work", released=True),
        _compaction("personal", released=True),  # released BUT personal -> blocked
        _compaction("personal", released=False),
    ]
    out = eligible_for_sync(compactions, sessions)
    synced_sessions = {c.session_id for c in out}
    assert "personal" not in synced_sessions
    assert synced_sessions == {"work"}
```

This test is a **foundational** security check: it ensures that no personal data, no matter how explicitly released, can pass the gate.

---

## 3. Redaction: What Leaves, What Stays

Redaction is applied **on the path to release** — the local store always keeps full fidelity; the engineer sees redacted previews before they opt in to sync. See `agent/src/manthana/agent/redaction/redactor.py`.

### Redaction Pipeline

The `Redactor` class detects and scrubs:

1. **Secrets (enabled by default, configurable in `manthana.toml`):**
   - AWS access keys (`AKIA...` or `ASIA...`)
   - Generic secrets (`secret=`, `password=`, `api_key: "..."`)
   - Private keys (`-----BEGIN PRIVATE KEY-----`)
   - JWTs (base64-encoded three-part tokens)
   - GitHub tokens (`gh_...`, `ghp_...`, etc.)

2. **PII (enabled by default, configurable):**
   - Email addresses (regex)
   - Phone numbers (US and intl formats)

3. **Governance detectors (copied verbatim from ECC):**
   - High-risk git commands (`git push --force`, `git reset --hard`)
   - Destructive operations (`rm -rf`, `DROP TABLE`, `DELETE FROM`)
   - Sensitive file paths (`.env.*`, `credentials`, `*.pem`, `*.key`, `id_rsa`)

All patterns are in `agent/src/manthana/agent/redaction/patterns.py`, with ECC attribution.

### What Is NOT Redacted: `_COMPACTION_KEEP`

The field `_COMPACTION_KEEP` in `redactor.py` lists fields that are **never redacted** because they are structural:

```python
_COMPACTION_KEEP = frozenset({
    "id",              # compaction identifier (needed for citations)
    "session_id",      # session reference (needed for joins)
    "actor",           # contributor identity (needed for k-anon)
    "surface",         # claude_code|codex|cursor (for filtering)
    "project",         # project name (grouping + k-anon)
    "kind",            # "base"|"engineering" (discriminator)
    "tier_used",       # model tier (for cost rollups)
    "outcome",         # success|partial|abandoned (filtering)
    "prompt_version",  # version tag
    "action_triggers", # action ids (grouping)
    "source",          # "full"|"claude_summary" (digests)
})
```

Everything else that is a string or list of strings **is redacted by default**, including:
- `task_intent` — what the engineer was trying to do
- `approach` — how they solved it
- `artifacts` — what was created
- `files_touched`, `prs_opened` (EngineeringCompaction fields) — specific file/PR names
- `friction_points[].description` — problem descriptions

The founding principle: redaction keeps the **structure** needed for grouping, filtering, and citation, but scrubs the **content** that reveals secrets and PII.

### Redaction at Sync Time

The `SyncClient` (in `agent/src/manthana/agent/sync_client.py`) redacts every compaction before uploading:

```python
redacted = self.redactor.redact_compaction(compaction)
ingested = self.push_compactions([redacted])
```

And raw transcripts (turns as JSONL) are also redacted before upload:

```python
redacted_turns = self.redactor.redact_turns(turns)
raw_content = "\n".join(turn.model_dump_json() for turn in redacted_turns)
self.push_raw(compaction_id, raw_content)
```

---

## 4. K-Anonymity: The Org Cannot Target Individuals

K-anonymity prevents the founder from querying down to a single engineer's data (which would violate the employee's privacy even if everything is redacted). The floor is set to **4 distinct contributors** (configurable in `MANTHANA_SERVER_K_ANON`; default 4).

### Global Floor

In the founder query (see `server/src/manthana/server/founder.py`), the rollup is suppressed entirely if the global contributor count is below the floor:

```python
def _rollup(compactions: list[Any], floor: int) -> tuple[Rollup, set[str], set[str]]:
    distinct_contributors = {c.actor for c in compactions}
    if len(distinct_contributors) < floor:
        return None, set(), set()  # insufficient data
```

A founder query returns **"insufficient data"** if fewer than 4 engineers contributed to the result set.

### Per-Bucket Floor

The founder query also supports filtering (by `project`, `outcome`, `surface`, etc.). Each sub-bucket (e.g., "success" outcomes from the Python project) is tested against the floor independently:

```python
by_project = defaultdict(int)
by_outcome = defaultdict(int)
for c in compactions:
    by_project[c.project] += 1
    by_outcome[c.outcome] += 1

# Suppress any sub-bucket with < floor contributors
suppressed_projects = {p for p, count in by_project.items() if count < floor}
suppressed_outcomes = {o for o, count in by_outcome.items() if count < floor}
```

If a sub-bucket has only 1–3 engineers, it is **not returned** in the narrative, even if the global count is high.

### Per-Filter Floor (Tracked v1.5)

The current implementation does not enforce a floor on *every* filter combination (e.g., "Python + success + actor=bob" might be only 1 engineer). This is tracked in `manthana-decisions.md` as a v1.5 hardening item; the current code already suppresses sub-buckets and collapses `actor` filters to "insufficient" when too specific.

### Skill Mining K-Anonymity

When mining skills across the org (see `server/src/manthana/server/app.py`, `POST /v1/admin/mine-skills`), only skills with **≥4 distinct contributors** are enqueued for approval. Contributor names are dropped in the org-level skill; they are kept only for personal skill mining (a single engineer).

---

## 5. Server Authentication & Authorization

All server endpoints require authentication. There are two credential types:

### Agent Authentication: Team-Scoped JWT

Engineers upload compactions to the server using a **team-scoped JWT** (JSON Web Token), issued by the admin at team onboarding.

**Token contents** (`auth.py`, `TeamClaims`):
- `sub` (subject): the engineer's email (e.g., `engineer@company.com`)
- `org`: the organization id
- `team`: the team id
- `scope`: always `"agent"` (marker for agent tokens vs other token types)
- `exp`: expiration timestamp (default 365 days)

**Token verification** at every agent endpoint:

```python
def require_team(authorization: Annotated[str, Header()] = "") -> TeamClaims:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return verify_team_token(config.jwt_secret, authorization.removeprefix("Bearer "))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
```

The token is read from the `Authorization: Bearer <token>` header (never in the URL or form body). The JWT library is configured to **require** the `exp` and identity claims (`sub`, `org`, `team`); a forged or non-expiring token is rejected immediately.

**Token binding to compactions** (in `server/store.py`):

When a compaction is ingested, it is tagged with the authenticated actor and team from the JWT:

```python
def ingest_compaction(
    self, compaction: BaseCompaction, *, org_id: str, team_id: str
) -> None:
    if not compaction.released:
        raise NotReleasedError(f"compaction {compaction.id} is not released")
    self.upsert_actor(compaction.actor, org_id, team_id)
    # ... stored with org_id, team_id from the verified token
```

This prevents an engineer from spoofing another engineer's work.

### Admin Authentication: Static Admin Token

Founder endpoints, team management, and the founder console are protected by a single **static admin token** (a long, random secret like `sk-...` or a UUID). This is passed in the `X-Admin-Token` header and compared using **constant-time comparison** (`hmac.compare_digest`) to prevent timing attacks:

```python
def require_admin(x_admin_token: Annotated[str, Header()] = "") -> None:
    if not hmac.compare_digest(x_admin_token, config.admin_token):
        raise HTTPException(status_code=401, detail="invalid admin token")
```

The admin token is **never passed on the command line** (it leaks into shell history and process lists). Instead, it is stored in a gitignored `.env` file, loaded by `scripts/serve.sh`:

```bash
set -a; source .env; set +a     # export everything in .env
uv run manthana-server serve --port 8000
```

### Founder Console: Cookie-Based Login

The founder web UI (`server/src/manthana/server/ui.py`) adds a second layer: **httponly cookies** set after a successful login via the admin token.

- `POST /ui/login` checks the admin token and sets an `httponly` cookie named `manthana_admin`.
- Every `/ui/*` route checks the cookie and **303-redirects to `/ui/login`** if absent, leaking no org data.
- `GET /ui/logout` (POST in current code) clears the cookie.

The cookie is bound to the `/ui` path and has the `httponly` flag, preventing JavaScript from reading it (defense against XSS).

---

## 6. Secrets at Rest

### On the Employee's Laptop

1. **`manthana.toml`** (at `$MANTHANA_DATA_HOME/manthana.toml`):
   - Contains the team JWT (stored by `manthana login`).
   - File is created with **mode 0o600** (owner read/write only) by `config.py`:
     ```python
     target.chmod(0o600)
     ```
   - The chmod is a best-effort operation; some filesystems (FAT, certain SMB shares, and Windows) don't support POSIX perms, so it is not a guarantee.

2. **`manthana.db`** (the local SQLite store at `$MANTHANA_DATA_HOME/manthana.db`):
   - SQLite stores all transcripts and compactions.
   - File permissions follow the parent directory's umask. If the data home is created with restrictive perms, the store is protected by OS-level access control.
   - On macOS/Linux, `umask 0077` (group/other inaccessible) is the secure default. On Windows, NTFS ACLs apply.

### On the Server

1. **JWT secret** (`MANTHANA_SERVER_JWT_SECRET`):
   - Used to sign and verify agent tokens.
   - Must be a cryptographically random secret (not the placeholder `dev-insecure-jwt-secret-change-me`).
   - Stored in the `.env` file (gitignored) or a secrets-management system (Vault, K8s Secrets, etc.).

2. **Admin token** (`MANTHANA_SERVER_ADMIN_TOKEN`):
   - Gating founder and team-management endpoints.
   - Must be a long random secret.
   - Stored in the `.env` file or secrets system.

3. **Database credentials** (if using Postgres in production):
   - Connection string in `MANTHANA_SERVER_DB_URL` (includes username/password).
   - Stored in `.env` or a secrets system.

4. **S3/MinIO credentials** (for raw transcript storage):
   - `MANTHANA_SERVER_S3_ACCESS_KEY` and `MANTHANA_SERVER_S3_SECRET_KEY`.
   - Stored in `.env` or secrets system.

### Secret Validation

The `ServerConfig.__post_init__` method (in `server/src/manthana/server/config.py`) **rejects the shipped insecure placeholders**:

```python
if self.admin_token == _DEV_ADMIN_TOKEN or self.jwt_secret == _DEV_JWT_SECRET:
    raise ValueError(
        "refusing to run with the insecure dev defaults — set "
        "MANTHANA_SERVER_ADMIN_TOKEN and MANTHANA_SERVER_JWT_SECRET "
    )
```

A production deployment cannot boot with the default secrets. Additionally, empty secrets are rejected (an empty admin token or JWT secret would authenticate any request due to `hmac.compare_digest("", "") == True`).

---

## 7. Server-Side Fail-Closed Checks

The server is hardened to prevent ingestion of unreleased or misclassified data.

### Release Check at Ingest

Only compactions with `released=True` are accepted by `POST /v1/compactions`:

```python
def ingest_compaction(
    self, compaction: BaseCompaction, *, org_id: str, team_id: str
) -> None:
    if not compaction.released:
        raise NotReleasedError(f"compaction {compaction.id} is not released")
```

An unreleased compaction in the sync batch triggers a **422 Unprocessable Entity** response; none of the batch is stored.

### Batch Atomicity

The entire batch is validated for release status **before any row is persisted**, ensuring an all-or-nothing outcome:

```python
# In app.py: POST /v1/compactions endpoint
for compaction_dict in body.compactions:
    compaction = CompactionAdapter.validate_python(compaction_dict)
    if not compaction.released:
        raise NotReleasedError(...)
# Only after all are validated:
for compaction in compactions:
    store.ingest_compaction(compaction, org_id=org_id, team_id=team_id)
```

### Cross-Tenant Isolation

Compaction primary keys on the server are **org-namespaced** (`{org_id}::{compaction_id}`), preventing id collisions between orgs:

```python
def _pk(org_id: str, compaction_id: str) -> str:
    return f"{org_id}::{compaction_id}"
```

All reads are **org-scoped** (and sensitive endpoints are also **team-scoped**):

```python
def get_compaction(self, compaction_id: str, org_id: str) -> BaseCompaction | None:
    """Org-scoped fetch of a released compaction."""
    with DBSession(self._engine) as db:
        row = db.get(ReleasedCompactionRow, _pk(org_id, compaction_id))
        if row is None or not row.released:
            return None
```

### Timezone Normalization

Timestamps are stored in UTC ISO format (`_utc_iso`) to prevent off-by-one errors in date queries:

```python
def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
```

Date ranges in founder queries treat `until` as a half-open upper bound (the whole boundary day is included):

```python
if "T" not in until and len(until) == 10:
    nxt = date.fromisoformat(until) + timedelta(days=1)
    return ("<", f"{nxt.isoformat()}T00:00:00+00:00")
```

---

## 8. Founder Query Grounding & Citations

The founder query is "**structured-filter-first, narrative-second**" — every claim must be grounded in the data, or the query returns "insufficient data" instead of an ungrounded answer.

### Pipeline

1. **Parse** the natural-language query into a structured filter (using the LLM):
   ```python
   filter = parse_filter(query, provider)
   ```

2. **SQL over released compactions** filtered by the structured filter:
   ```python
   compactions = store.query_compactions(
       org_id=org_id,
       team_id=filter.team_id,
       project=filter.project,
       ...
   )
   ```

3. **K-anonymity check** — if fewer than 4 distinct contributors, return "insufficient data".

4. **Narrative generation** using the LLM, instructed to cite every claim:
   ```python
   narrative = provider.complete(
       f"Write a 2-4 sentence summary... Cite the specific compaction id "
       f"in [square brackets] for EVERY claim; do not invent facts."
   )
   ```

5. **Citation matching** — extract all `[cited-ids]` from the narrative and resolve each to a real compaction id:
   ```python
   cited = _match_citations(narrative, compactions)
   ```

6. **Grounding check** — if the narrative cites nothing, or cites ambiguous prefixes, return "insufficient data".

### Citation Matching Algorithm

Real models abbreviate long UUID compaction ids and sometimes group several ids in one bracket. The `_match_citations` function in `founder.py` resolves this robustly:

```python
def _match_citations(narrative: str, visible: list[Any]) -> list[str]:
    """Resolve bracketed citations by exact-or-unique-prefix match."""
    pieces = set()
    for token in _CITE_RE.findall(narrative):  # extract [...]
        for part in re.split(r"[,\s]+", token.strip()):  # split on comma/space
            if part:
                pieces.add(part)
    ids = [c.id for c in visible]
    matched = set()
    for piece in pieces:
        hits = [cid for cid in ids if cid == piece or cid.startswith(piece)]
        if len(hits) == 1:  # unambiguous — unique prefix or exact
            matched.add(hits[0])
    return [cid for cid in ids if cid in matched]
```

An ambiguous prefix (matching >1 compaction id) is **dropped** — grounding is conservative and never grounds to the wrong compaction.

### Graceful Degradation

If the LLM provider raises an exception (rate limit, network error, auth failure), both the filter parse and the narrative generation **degrade gracefully** — no 500 error, no SDK exception leaked to the client:

```python
try:
    raw = provider.complete(_PARSE_PROMPT.format(query=query))
except Exception:
    _log.exception("founder filter parse: provider call failed")
    return FounderFilter()  # empty filter (match all)

try:
    narrative = provider.complete(...)
except Exception:
    _log.exception("founder narrative: provider call failed")
    return insufficient_data_result()  # "insufficient data" returned
```

---

## 9. Founder Query Audit Log (Tracked v1.5)

A dedicated audit log table (`FounderQueryAuditRow` in `server/src/manthana/server/tables.py`) tracks founder queries for compliance:

- **Who** queried (authenticated admin identity, if derivable)
- **When** (timestamp)
- **Which org** (org_id)
- **Query text** (the NL question)
- **Filter** (the parsed structured filter)
- **Compaction IDs cited** in the result
- **Result** (narrative or "insufficient data")

This is scaffolded in the schema but the endpoint (`/v1/founder/audit`) that surfaces the log is deferred to v1.5 to avoid scope creep in the server phase. The mechanism is in place; the UI is pending.

---

## 10. Personal Mode Deep Dive

Personal-mode sessions are the engineer's scratch space. They:

- **Do not sync** — blocked by `eligible_for_sync` before any transport.
- **Do not trigger actions** — the dispatcher skips them:
  ```python
  if session.mode is Mode.personal:
      return "personal_mode_excluded"  # hard skip
  ```
- **Do not reach any team report** — k-anon floors and the founder query exclude them.
- **Cannot be opted out of** — there is no "release this personal session" override. Once toggled to Personal, it is locked out of all org-level flows.

The toggle is in the dashboard (`/` page, one-click Work ↔ Personal) and CLI (`manthana mode <session_id> work|personal`). The local store records the mode in the `Session.mode` column.

---

## 11. Trust Gate Architecture Diagram

```mermaid
graph TD
    A["Engineer's Laptop<br/>(manthana.db)"] -->|"manthana sync"| B["Sync Gate<br/>eligible_for_sync"]
    B -->|"✗ personal_mode"| A
    B -->|"✗ not_released"| A
    B -->|"✗ no_session"| A
    B -->|"✓ work + released"| C["Redactor<br/>(secrets/PII scrub)"]
    C -->|"Redacted Compaction"| D["HTTP POST<br/>(JWT auth)"]
    D -->|"Bearer token"| E["Server<br/>(AGPL)"]
    E -->|"Verify JWT<br/>Org-scope PKs<br/>Release check"| F["released_compaction table"]
    F -->|"Released data only"| G["Founder Query<br/>K-anon floor ≥4"]
    G -->|"Parse filter<br/>SQL result<br/>Grounded narrative"| H["Founder Console<br/>(Admin token auth)"]
    H -->|"Read-only view"| I["Founder"]

    style A fill:#e1f5ff
    style B fill:#fff3e0
    style C fill:#f3e5f5
    style D fill:#e8f5e9
    style E fill:#fce4ec
    style F fill:#f1f8e9
    style G fill:#fff9c4
    style H fill:#e0f2f1
```

---

## 12. Deployment Hardening

### Docker Image

The server is shipped as a non-root container image (`ghcr.io/suraj-gameramp/manthana-server`) in `deploy/Dockerfile`. The image:

- Runs as a non-root user (UID 1000, e.g., `manthana`).
- Includes `/healthz` and `/readyz` liveness/readiness probes (consumed by compose/k8s).
- Binds to a configurable port (default 8000) and environment variables.

### Docker Compose Overlay

A `.env` file and `docker-compose.prod.yml` overlay provide production configuration:

- Postgres database (separate service, not SQLite).
- MinIO (S3-compatible object store for raw transcript storage).
- Network isolation (services on a private network; only the reverse proxy/gateway exposes the server).

The compose stack does **not** auto-load secrets from environment; admins must provide `.env` explicitly.

### Kubernetes Manifests

The `deploy/k8s/` directory contains resource manifests:

- Non-root Pod SecurityContext.
- ServiceAccount + RBAC bindings (minimal read-only access).
- Liveness/readiness probes (`GET /healthz`, `GET /readyz`).
- Secret mounting (JWT secret, admin token, DB credentials as K8s Secrets).
- Resource limits (CPU, memory).

---

## 13. Configuration Checklist for Ops

Before deploying to production, ensure:

1. **Secrets set (not defaults):**
   - `MANTHANA_SERVER_JWT_SECRET` ≠ `dev-insecure-jwt-secret-change-me`
   - `MANTHANA_SERVER_ADMIN_TOKEN` ≠ `dev-admin-token`
   - `MANTHANA_SERVER_DB_URL` points to a production Postgres instance with strong credentials.
   - `MANTHANA_SERVER_S3_*` credentials (if using S3/MinIO for raw transcripts).

2. **K-anonymity floor set:**
   - `MANTHANA_SERVER_K_ANON` (default 4; do not lower below 4 without explicit risk acceptance).

3. **LLM provider configured:**
   - `MANTHANA_SERVER_LLM=mock` (dev) or `anthropic` (production).
   - If `anthropic`: `ANTHROPIC_API_KEY` set, `MANTHANA_SERVER_LLM_MODEL` tuned for your use case (default `claude-sonnet-4-6` is cost-sensible; `claude-opus-4-8` is stronger).

4. **Network hardening:**
   - The server is bound to `0.0.0.0` by default (all interfaces). In production, bind to `127.0.0.1` if a reverse proxy (nginx, Caddy) is in front, or use a LoadBalancer service in k8s.
   - TLS is not terminated by Manthana; use a reverse proxy or managed load balancer (AWS ALB, GCP Cloud Load Balancer, etc.).

5. **Audit logging:**
   - The founder-query audit log is available in `FounderQueryAuditRow` (v1.5 UI pending).
   - Logs are emitted to stdout/stderr (captured by container orchestration).

6. **Backups:**
   - Postgres snapshots (RDS, managed Postgres, or manual `pg_dump`).
   - S3/MinIO buckets (versioning enabled, cross-region replication if required).

---

## 14. Related Documents

- **[spec/manthana-architecture.md](spec/manthana-architecture.md)** — the realized code-grounded architecture (file paths, schema reference, phase status).
- **[spec/manthana-decisions.md](spec/manthana-decisions.md)** — locked decisions and the build order; overrides any other doc on conflict.
- **[docs/deploy.md](docs/deploy.md)** — operational guide for deploying the full stack.
- **[docs/onboarding.md](docs/onboarding.md)** — engineer onboarding workflow (login, service install, dashboard intro).

---

## 15. Incident Response

If you suspect a breach or unauthorized access:

1. **Agent-side leak (personal data synced by mistake):**
   - Run `tests/test_personal_mode_invariant.py` to verify the gate is not bypassed.
   - Check `store.py` to see if `eligible_for_sync` is called at all egress points.
   - Rotate the team JWT immediately (`manthana-server token --org <org_id> --team <team_id> --actor <actor>`).

2. **Server-side unauthorized access:**
   - Rotate the admin token (`MANTHANA_SERVER_ADMIN_TOKEN`).
   - Rotate the JWT secret (`MANTHANA_SERVER_JWT_SECRET`); reissue all team tokens.
   - If S3/MinIO credentials are leaked, rotate them and re-upload a clean copy of released transcripts.

3. **Secrets in transcripts (despite redaction):**
   - A secret that made it into a compaction (e.g., a missed regex pattern) will be redacted on egress, so the org server does not see it.
   - If the engineer suspects a secret is already in the local store, they should:
     1. Delete the affected sessions (`manthana delete <session_id>`).
     2. Invalidate any local JWT tokens.
     3. Rotate the actual secret at its source (API provider, cloud service, etc.).

---

## Summary

Manthana's trust model is **employee-first**: the engineer owns their data, decides what to release, and the org never sees personal sessions or unreleased work. The single gate `eligible_for_sync` enforces this from code; redaction and k-anonymity scrub secrets and prevent targeting; and authentication (JWT for agents, static token for admins) ties all server changes to a verified identity. This design makes the trust boundary explicit and testable — not a "trust me" black box, but a contract verified by tests and hardened through adversarial review.
