# Data Model and Schemas

Pydantic v2 contract models, discriminated-union polymorphism, document-store-with-indexes persistence, and multi-tenant server tables.

---

## Overview

Manthana separates the data contract (validation, interoperability) from persistence (local SQLite or server Postgres). All domain models live in `manthana.schemas` (Apache-2.0, distributed separately) as pure Pydantic BaseModel subclasses; the local and server stores materialize them into SQL tables using a **document-store-with-indexes pattern** — each row carries typed index columns (for `WHERE`/`ORDER BY`) plus an authoritative `data` JSON column holding the full model dump. When a row is loaded, the domain object is reconstructed via `model_validate(row.data)` so the table schema never drifts from the contract.

**Polymorphism via discriminated unions:** `BaseCompaction` and `EngineeringCompaction` are joined by a `kind` discriminator; a `CompactionAdapter` TypeAdapter handles mixed deserialization. The store can persist and query both in a single table.

---

## Core Schemas (`manthana.schemas`)

### Turn

A single atomic unit of an AI session—surface-agnostic, flattened from raw transcript lines.

```python
class Turn(BaseModel):
    id: str                              # Stable unique id
    session_id: str                      # Owning session
    actor: str                           # Engineer identity (e.g. org email)
    seq: int                             # Monotonic order within session
    timestamp: datetime | None           # Event time (sparse on meta lines)
    role: Role                           # user | assistant | tool
    
    content: str | None                  # Text content, if any
    
    tool_name: str | None                # Tool name (call or result)
    tool_input: dict[str, Any] | None    # Tool call arguments
    tool_output: str | None              # Tool result content
    tool_use_id: str | None              # Pairs call ↔ result via ID
    
    model: str | None                    # Model id (assistant turns)
    tokens_in: int | None                # Input tokens
    tokens_out: int | None               # Output tokens
    cache_creation_tokens: int | None    # Prompt-cache creation
    cache_read_tokens: int | None        # Prompt-cache reads
    
    error: str | None                    # Error string (e.g. tool failure)
    
    # Provenance (documented Manthana extension): map back to raw
    # transcript for citations & cross-line tool pairing.
    source_event_id: str | None          # Raw transcript uuid
    source_parent_id: str | None         # Raw transcript parentUuid
```

**Flattening rules:** A raw Claude Code line may produce several Turns:

- Plain user text → `Turn(role=user, content=text)`
- Assistant text block → `Turn(role=assistant, content=text, model=..., tokens=...)`
- Assistant `tool_use` block → `Turn(role=assistant, tool_name, tool_input, tool_use_id)`
- User `tool_result` block → `Turn(role=tool, tool_output, tool_use_id)` (paired to call)

See `turn.py` field map for the Claude Code JSONL→Turn mapping.

### Session

A contiguous block of Turns on one surface (Claude Code, Codex, etc.), with Work/Personal mode and optional resumption linkage.

```python
class Session(BaseModel):
    id: str                              # Stable session id
    actor: str                           # Engineer identity
    surface: Surface                     # claude_code | codex | cursor
    project: str                         # Inferred project name
    repo_root: str | None                # git rev-parse --show-toplevel
    
    started_at: datetime
    ended_at: datetime | None
    ended_reason: SessionEndReason       # gap | stop_hook | cap | open
    
    turn_count: int = 0
    mode: Mode = Mode.work               # work | personal (personal never syncs)
    
    resumed_from: str | None             # Prior session id if --resume crossed 30-min window
    source_path: str | None              # Transcript file path this was parsed from
    
    has_compact_summary: bool = False    # Transcript carries Claude's own compaction
    tags: dict[str, str] = {}            # Auto-tag action output (project/task/outcome/friction)
```

**Session boundaries** (from decisions doc):

- `>30 min gap` since last turn
- Clean exit / Stop hook fired
- `>6 h` continuous activity (forced cap)

**Trust contract:** The `mode` field controls sync eligibility; `personal` sessions never leave the laptop (enforced by `manthana.agent.sync.eligible_for_sync` and guarded by `tests/test_personal_mode_invariant.py`).

### BaseCompaction

Typed digest of a single session. The parent class; `EngineeringCompaction` extends it for v1.

```python
class BaseCompaction(BaseModel):
    kind: Literal["base"] = "base"
    
    id: str                              # Stable compaction id
    session_id: str
    actor: str
    surface: Surface
    project: str
    
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    
    task_intent: str                     # What they set out to do
    approach: str                        # How they went about it
    artifacts: list[str] = []            # Things produced
    outcome: Outcome                     # success | partial | abandoned
    friction_points: list[FrictionPoint] = []
    
    tier_used: str | None                # Dominant model tier
    est_cost_usd: float | None = None    # Estimated cost
    reusable_pattern: bool = False
    
    # Trust contract: released flag gates raw transcript upload to object store.
    released: bool = False
    released_at: datetime | None = None
    
    # Architectural seam: action ids this should fire on next sync.
    action_triggers: list[str] = []
    
    # Documented Manthana extensions.
    prompt_version: str = "v0"           # Compaction prompt template version
    schema_version: int = 1
    created_at: datetime | None = None
    # How produced: "full" (from raw turns) or "claude_summary" (cheap, from Claude's summary)
    source: Literal["full", "claude_summary"] = "full"
```

### EngineeringCompaction

Engineering-role compaction (v1). Sales/Design deferred to v2; HR indefinitely deferred.

```python
class EngineeringCompaction(BaseCompaction):
    kind: Literal["engineering"] = "engineering"
    
    files_touched: list[str] = []
    prs_opened: list[str] = []
    tests_added: list[str] = []
    dead_end_branches: list[str] = []
    languages: list[str] = []
    frameworks: list[str] = []
```

### Compaction Polymorphism

```python
# Discriminated union keyed on 'kind'
Compaction = Annotated[
    EngineeringCompaction | BaseCompaction,
    Field(discriminator="kind"),
]

# TypeAdapter for mixed-stream deserialization
CompactionAdapter: TypeAdapter[BaseCompaction] = TypeAdapter(Compaction)

# Use: CompactionAdapter.validate_python(data) -> EngineeringCompaction | BaseCompaction
```

### FrictionPoint

A single friction event, evidenced by specific turns.

```python
class FrictionPoint(BaseModel):
    category: FrictionCategory           # loop | tool_error | abandon | retry | deadend
    description: str
    turn_refs: list[str] = []            # Turn ids that evidence this friction
```

### Action Seam Schemas

Architectural seams present in v1 even though most handlers ship v1.5+.

#### Action

Definition of a Manthana action type (the registry/catalog entry).

```python
class Action(BaseModel):
    id: str                              # Stable action id, e.g. 'auto_tag_sessions'
    name: str
    shape: ActionShape                   # read | write | warn | notify
    actor: ActionActor                   # engineer | org
    consent_class: ConsentClass          # silent | opt_out | opt_in | per_action
    version: str = "0.1.0"
    enabled: bool = True
    confidence_threshold: float | None = None  # Minimum signal to fire
    cooldown_seconds: int | None = None       # Min seconds between fires
    description: str = ""
```

#### ActionAuditEntry

Audit log seam: logged for every fired action AND every suppression (so actions are correctable, not authoritative).

```python
class ActionAuditEntry(BaseModel):
    id: str
    action_id: str
    actor: str | None = None             # Subject the action acted for/on
    fired_at: datetime
    trigger_condition: str               # Human-readable trigger that matched
    confidence: float | None = None
    outcome: ActionOutcome               # fired | suppressed | failed
    useful: bool | None = None           # Feedback (useful/not-useful)
    details: dict[str, Any] = {}
```

#### ActionQueueItem

Server-side pending action awaiting human approval. Empty in v1; populated in v1.5+.

```python
class ActionQueueItem(BaseModel):
    id: str
    action_id: str
    team_id: str | None = None
    payload: dict[str, Any] = {}
    status: QueueStatus = QueueStatus.pending   # pending | approved | rejected
    created_at: datetime
    approved_by: str | None = None
    resolved_at: datetime | None = None
```

### ConsentEntry

Consent registry seam. Per-engineer and per-admin opt-in/opt-out state per action.

```python
class ConsentEntry(BaseModel):
    id: str
    subject: str                         # Actor id (engineer) or 'org' / 'admin:<id>'
    action_category: str                 # Action id or category
    state: ConsentState = ConsentState.default  # opt_in | opt_out | default
    scope: str = "engineer"              # engineer | org
    set_at: datetime
```

---

## Enumerations

All controlled vocabularies as `StrEnum` in `enums.py`:

| Enum | Values | Purpose |
|---|---|---|
| `Surface` | `claude_code`, `codex`, `cursor` | Tool surface a session was captured from |
| `Role` | `user`, `assistant`, `tool` | Role of a normalized turn (`tool` = tool result) |
| `Mode` | `work`, `personal` | Work/Personal classification (personal never syncs) |
| `Outcome` | `success`, `partial`, `abandoned` | Terminal outcome of a session |
| `FrictionCategory` | `loop`, `tool_error`, `abandon`, `retry`, `deadend` | Categories of friction |
| `SessionEndReason` | `gap`, `stop_hook`, `cap`, `open` | Why a session boundary was drawn |
| `CompactionKind` | `base`, `engineering` | Discriminator for compaction polymorphism |
| `ActionShape` | `read`, `write`, `warn`, `notify` | What shape an action takes |
| `ActionActor` | `engineer`, `org` | Who performs an action |
| `ConsentClass` | `silent`, `opt_out`, `opt_in`, `per_action` | Consent class an action requires |
| `ConsentState` | `opt_in`, `opt_out`, `default` | Per-subject consent state |
| `ActionOutcome` | `fired`, `suppressed`, `failed` | Outcome when an action is evaluated |
| `QueueStatus` | `pending`, `approved`, `rejected` | Status of a server-side queued action |

---

## Local Store Tables

**Location:** `$MANTHANA_DATA_HOME/manthana.db` (SQLite)

**Pattern:** Each table carries typed **index columns** (for `WHERE`/`ORDER BY`) plus an authoritative `data` JSON column. Domain objects are reconstructed via `Session.model_validate(row.data)`.

### SessionRow

```python
class SessionRow(SQLModel, table=True):
    __tablename__ = "session"
    
    id: str                              # PK
    actor: str                           # indexed
    surface: str                         # indexed
    project: str                         # indexed
    mode: str                            # indexed
    started_at: str                      # ISO-8601, indexed (lexically sortable)
    ended_at: str | None
    resumed_from: str | None             # indexed
    turn_count: int = 0
    data: dict[str, Any]                 # Full Session model dump (JSON)
```

### TurnRow

```python
class TurnRow(SQLModel, table=True):
    __tablename__ = "turn"
    
    id: str                              # PK
    session_id: str                      # indexed
    actor: str                           # indexed
    seq: int                             # indexed
    role: str                            # indexed
    timestamp: str | None                # ISO-8601
    data: dict[str, Any]                 # Full Turn model dump (JSON)
```

### CompactionRow

```python
class CompactionRow(SQLModel, table=True):
    __tablename__ = "compaction"
    
    id: str                              # PK
    session_id: str                      # indexed
    actor: str                           # indexed
    project: str                         # indexed
    surface: str                         # indexed
    kind: str                            # indexed (base | engineering)
    outcome: str                         # indexed
    released: bool = False               # indexed (trust contract)
    started_at: str                      # ISO-8601, indexed
    tier_used: str | None
    est_cost_usd: float | None
    data: dict[str, Any]                 # Full compaction (Base or Engineering) as JSON
```

**Note:** Polymorphic storage via `CompactionAdapter.validate_python(row.data)` — the `kind` field determines deserialization to `EngineeringCompaction` or `BaseCompaction`.

### ActionAuditRow

```python
class ActionAuditRow(SQLModel, table=True):
    __tablename__ = "action_audit"
    
    id: str                              # PK
    action_id: str                       # indexed
    actor: str | None                    # indexed
    fired_at: str                        # ISO-8601, indexed
    outcome: str                         # indexed (fired | suppressed | failed)
    data: dict[str, Any]                 # Full ActionAuditEntry (JSON)
```

### ConsentRow

```python
class ConsentRow(SQLModel, table=True):
    __tablename__ = "consent"
    
    id: str                              # PK
    subject: str                         # indexed
    action_category: str                 # indexed
    state: str                           # indexed
    data: dict[str, Any]                 # Full ConsentEntry (JSON)
```

### SyncStateRow

Tracks which compactions and raw transcripts have synced to the org server. Metadata and raw are tracked separately.

```python
class SyncStateRow(SQLModel, table=True):
    __tablename__ = "sync_state"
    
    compaction_id: str                   # PK
    synced_at: str | None                # ISO-8601 (metadata synced)
    raw_synced_at: str | None            # ISO-8601 (raw transcript synced)
```

---

## Server Tables

**Location:** Postgres (prod) or SQLite (dev), provisioned by `manthana-server`

**Tenancy:** Org > Team > Actor; Project is a tag. All server rows are org-scoped. PKs are org-namespaced (`org::id`) to prevent cross-tenant collisions.

**Pattern:** Same document-store-with-indexes pattern as local store—typed index columns + `data` JSON.

### Multi-Tenancy Core

```python
class OrgRow(SQLModel, table=True):
    __tablename__ = "org"
    id: str                              # PK
    name: str
    created_at: str

class TeamRow(SQLModel, table=True):
    __tablename__ = "team"
    id: str                              # PK
    org_id: str                          # indexed
    name: str

class ActorRow(SQLModel, table=True):
    __tablename__ = "actor"
    id: str                              # PK (org email)
    org_id: str                          # indexed
    team_id: str                         # indexed
    display_name: str | None
```

### ReleasedCompactionRow

Persisted compaction (Base or Engineering). Stores only `released=True` rows.

```python
class ReleasedCompactionRow(SQLModel, table=True):
    __tablename__ = "released_compaction"
    
    id: str                              # PK (org::uuid format)
    org_id: str                          # indexed (org-scoped)
    team_id: str                         # indexed
    actor: str                           # indexed
    project: str                         # indexed
    surface: str                         # indexed
    outcome: str                         # indexed
    started_at: str                      # UTC ISO-8601, indexed
    kind: str                            # indexed
    released: bool = False               # indexed
    tier_used: str | None
    est_cost_usd: float | None
    data: dict[str, Any]                 # Full compaction (JSON)
```

### RawTranscriptRow

Raw-transcript artifact store (S3/MinIO metadata).

```python
class RawTranscriptRow(SQLModel, table=True):
    __tablename__ = "raw_transcript"
    
    id: str                              # PK
    compaction_id: str                   # indexed
    org_id: str                          # indexed
    object_key: str                      # S3/MinIO key
    uploaded_at: str                     # ISO-8601
```

### ActionQueueRow

Pending org action awaiting human approval (seam; empty in v1).

```python
class ActionQueueRow(SQLModel, table=True):
    __tablename__ = "action_queue"
    
    id: str                              # PK
    action_id: str                       # indexed
    org_id: str                          # indexed
    team_id: str | None                  # indexed
    status: str                          # indexed (pending | approved | rejected)
    created_at: str                      # ISO-8601
    data: dict[str, Any]                 # Full ActionQueueItem (JSON)
```

### OrgConsentRow

Org/admin-level consent registry (seam).

```python
class OrgConsentRow(SQLModel, table=True):
    __tablename__ = "org_consent"
    
    id: str                              # PK
    org_id: str                          # indexed
    subject: str                         # indexed
    action_category: str                 # indexed
    state: str                           # indexed
    data: dict[str, Any]                 # Full ConsentEntry (JSON)
```

### FounderQueryAuditRow

Audit trail of founder queries (governance + investigation).

```python
class FounderQueryAuditRow(SQLModel, table=True):
    __tablename__ = "founder_query_audit"
    
    id: str                              # PK
    org_id: str                          # indexed
    query: str                           # NL question (truncated)
    insufficient: bool                   # indexed (withheld vs answered)
    citation_count: int                  # Number of cited compactions
    created_at: str                      # ISO-8601, indexed
    data: dict[str, Any]                 # Cited ids, etc. (JSON)
```

---

## Store APIs

### Local Store (`manthana.agent.store.Store`)

**Sessions:**
- `upsert_session(session: Session)` → `None`
- `get_session(session_id: str)` → `Session | None`
- `list_sessions(*, actor, project, surface, mode, limit)` → `list[Session]`
- `set_session_mode(session_id: str, mode: Mode)` → `None`
- `update_session_tags(session_id: str, tags: dict)` → `None`

**Turns:**
- `add_turns(turns: Iterable[Turn])` → `None`
- `get_turns(session_id: str)` → `list[Turn]`
- `count_turns(session_id: str)` → `int`

**Compactions:**
- `upsert_compaction(compaction: BaseCompaction)` → `None`
- `get_compaction(compaction_id: str)` → `BaseCompaction | None`
- `list_compactions(*, session_id, actor, released, limit)` → `list[BaseCompaction]`
- `mark_released(compaction_id: str)` → `None`

**Actions & Consent:**
- `add_audit(entry: ActionAuditEntry)` → `None`
- `list_audit(*, action_id, actor)` → `list[ActionAuditEntry]`
- `last_fired_at(action_id: str)` → `datetime | None` (for cooldown)
- `get_consent(subject: str, action_category: str)` → `ConsentEntry | None`
- `set_consent(entry: ConsentEntry)` → `None`
- `list_consent(subject: str)` → `list[ConsentEntry]`

**Sync state:**
- `mark_synced(compaction_id: str)` → `None`
- `synced_ids()` → `set[str]`

### Server Store (`manthana.server.store.ServerStore`)

**Compaction ingestion:**
- `ingest_compaction(org_id: str, team_id: str, compaction: BaseCompaction)` → org-scoped row
- `query_compactions(org_id: str, *, filters)` → `list[BaseCompaction]` (org-scoped)
- `get_owned_compaction(org_id: str, team_id: str, compaction_id: str)` → `BaseCompaction | None` (fail-closed)

**Raw transcript:**
- `record_raw(org_id: str, compaction_id: str, object_key: str)` → `None`

**Multi-tenancy:**
- `list_orgs()` → `list[OrgRow]`
- `list_teams(org_id: str)` → `list[TeamRow]`
- `count_compactions(org_id: str)` → `int` (released only)

---

## Data Flow Diagram

```mermaid
graph TB
    subgraph "Contract (manthana.schemas)"
        Turn["Turn"]
        Session["Session"]
        BaseCompaction["BaseCompaction"]
        EngineeringCompaction["EngineeringCompaction<br/>(v1)"]
        FrictionPoint["FrictionPoint"]
        Action["Action"]
        ActionAudit["ActionAuditEntry"]
        ConsentEntry["ConsentEntry"]
    end
    
    subgraph "Local Store (SQLite)"
        TurnRow["TurnRow<br/>(index cols + data JSON)"]
        SessionRow["SessionRow<br/>(index cols + data JSON)"]
        CompactionRow["CompactionRow<br/>(index cols + data JSON)"]
        ActionAuditRow["ActionAuditRow<br/>(index cols + data JSON)"]
        ConsentRow["ConsentRow<br/>(index cols + data JSON)"]
        SyncStateRow["SyncStateRow"]
    end
    
    subgraph "Server Store (Postgres)"
        ReleasedCompactionRow["ReleasedCompactionRow<br/>(org::id, index cols + data JSON)"]
        RawTranscriptRow["RawTranscriptRow"]
        ActionQueueRow["ActionQueueRow<br/>(seam)"]
        OrgConsentRow["OrgConsentRow<br/>(seam)"]
        FounderQueryAuditRow["FounderQueryAuditRow<br/>(governance)"]
    end
    
    subgraph "Compaction Polymorphism"
        CompactionAdapter["CompactionAdapter<br/>(TypeAdapter, kind discriminator)"]
    end
    
    Turn --> TurnRow
    Session --> SessionRow
    BaseCompaction --> CompactionRow
    EngineeringCompaction --> CompactionAdapter
    CompactionAdapter --> CompactionRow
    FrictionPoint --> BaseCompaction
    Action --> ActionAuditRow
    ActionAudit --> ActionAuditRow
    ConsentEntry --> ConsentRow
    
    CompactionRow --|eligible_for_sync<br/>redact<br/>POST /v1/compactions| ReleasedCompactionRow
    CompactionRow --|raw release| RawTranscriptRow
    
    ReleasedCompactionRow --|founder query<br/>k-anon filter| FounderQueryAuditRow
    
    ActionAuditRow --> ActionQueueRow
    ConsentRow --> OrgConsentRow
```

---

## Key Design Decisions

### Document-Store-with-Indexes Pattern

Reexpresses ECC's schema-validated JSON-document store. The rationale:

- **Validation is in the contract** (`manthana.schemas`, distributed separately) — DB-agnostic.
- **Persistence is in the store** — each row's `data` JSON is the authoritative model; index columns are projections.
- **Polymorphism is trivial** — CompactionAdapter deserialization handles discriminated unions automatically; no FK/cascade complexity.
- **Schema evolution is incremental** — new fields land in the contract; old stores don't break (old rows stay valid; new code produces new fields).

### Polymorphic Compactions via Discriminated Union

```python
Compaction = Annotated[
    EngineeringCompaction | BaseCompaction,
    Field(discriminator="kind"),
]
```

The `kind` field (`"base"` or `"engineering"`) is the discriminator. `CompactionAdapter` decodes mixed streams correctly:

```python
data = {"kind": "engineering", "id": "...", ...}
compaction = CompactionAdapter.validate_python(data)  # → EngineeringCompaction
```

Sales/Design roles are deferred to v2 — just add new subclasses to the `Compaction` union without touching the store layer.

### Org-Namespaced PKs on the Server

Server compaction IDs use the format `org::uuid` to prevent cross-tenant collisions and enforce org-scoped reads:

```python
# Bad: an engineer in Org A crafts a compaction id
# and forges a claim that it belongs to Org B.
# 
# Good: the server rejects it (owns lookup fails) and logs an audit event.
get_owned_compaction(org_id="B", compaction_id="A::uuid")  # → None (404)
```

---

## Cross-References

- **Architecture:** See `spec/manthana-architecture.md` §4 (schema reference), §4a (local store), §12-13 (server), §18 (miner→server).
- **Decisions:** See `spec/manthana-decisions.md` — locked data model, trust contract, capture rules.
- **Capture:** See `spec/manthana-architecture.md` §4b (Claude Code collector, sessionization, Turn flattening).
- **Sync chokepoint:** `manthana.agent.sync.eligible_for_sync` — the single gate all egress passes through; guarded by `tests/test_personal_mode_invariant.py`.
- **Redaction:** `manthana.agent.redaction.Redactor` — applied on release to all free-text fields, never stored locally.

---

## Index Columns Strategy

All timestamps are stored as **UTC ISO-8601 strings** in index columns (`started_at`, `fired_at`, `created_at`), so lexical `ORDER BY` is chronologically correct across mixed timezones:

```python
def _utc_iso(value: datetime) -> str:
    """UTC ISO-8601 for index columns, so lexical TEXT ordering is chronological."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
```

This ensures `ORDER BY started_at DESC` returns sessions in reverse chronological order, even if sessions were started in different timezones.

---

## Versioning

- **`schema_version`** on compactions: currently `1`; incremented on structural changes.
- **`prompt_version`** on compactions: currently `v0`; incremented as the compaction prompt template improves.
- **`source`** on compactions: `"full"` (from raw turns) or `"claude_summary"` (cheaply, from Claude Code's own compaction summary). Allows Ask/founder endpoints to prefer the cheapest source with a toggle.
- **Action `version`**: Semver for action definitions; handlers may be updated independently.

---

## Constraints & Validation

All Pydantic models are configured with `extra="forbid"` — unknown fields in JSON are rejected. This maintains contract integrity across upgrades.

Personal-mode sessions (`mode == Mode.personal`) are excluded from:
- Sync (via `eligible_for_sync`)
- Actions (via dispatcher)
- All founder queries (server-side filter)

The `released` flag gates raw-transcript upload; the server rejects unreleased compactions at ingest.

K-anonymity floor: `k_anon_floor = 4` (global + per-project/outcome bucket). Sub-floor cohorts are suppressed in founder narratives; org mining requires ≥4 distinct contributors.
