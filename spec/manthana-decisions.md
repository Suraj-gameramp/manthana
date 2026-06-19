# Manthana Decisions Lock

*Single-page reference of locked decisions for v1 build. Companion to* `manthana-spec.md`, `manthana-ecc-reuse-list.md`, `manthana-actions.md`. *If something here conflicts with the longer docs, this document wins for v1.*

---

## Identity

- **Name:** Manthana
- **License:** AGPL-3.0 (server), Apache-2.0 (collectors, client tooling, SDKs)
- **Repo:** mono-repo; sub-packages for `agent/`, `server/`, `collectors/`, `schemas/`, `tests/`, `docs/`
- **Attribution to ECC:** `LICENSES/MIT-ECC.txt` retains original MIT copyright; `NOTICE` file credits ECC for vendored components

## Language and stack

- **Python 3.11+** for everything (local agent, server, collectors, CLI)
- **FastAPI** for the server (async, OpenAPI built-in)
- **SQLModel** for ORM (combines SQLAlchemy and Pydantic; one model class for both validation and DB)
- **asyncio** for concurrency
- **Pydantic v2** for all schema definitions in Python
- **JSON Schema** mirrored from Pydantic models for cross-language reuse and CI validation
- **typer** for CLI
- **uv** for package management
- **ruff** for lint; **pyright** for type-check
- **pytest** + **pytest-asyncio** for tests
- **anthropic** and **openai** SDKs available but not required (compactor uses engineer's existing CLI access, not direct SDK calls)
- **sentence-transformers** for local embeddings
- **sqlite-vec** for local vector store; **pgvector** on the server

## Storage

- **Local agent:** SQLite, single file at `$MANTHANA_DATA_HOME/manthana.db`
- **Org server:** Postgres for compactions and metadata; S3-compatible object store (MinIO for self-hosted; AWS S3 / GCS / R2 for cloud) for raw transcripts released on explicit approval

## Data model (v1)

**Entities:** `Turn`, `Session`, `BaseCompaction`, `EngineeringCompaction`, `Action`, `ConsentEntry`

**Turn fields:** `id, session_id, actor, timestamp, role (user|assistant|tool), content, tool_name?, tool_input?, tool_output?, model?, tokens_in?, tokens_out?, cache_creation_tokens?, cache_read_tokens?, error?`

**Session fields:** `id, started_at, ended_at?, actor, surface (claude_code|cursor|codex), project (string), repo_root, turn_count, mode (work|personal)`

**BaseCompaction fields:** `session_id, actor, surface, project, started_at, ended_at, duration_seconds, task_intent, approach, artifacts, outcome (success|partial|abandoned), friction_points, tier_used, est_cost_usd, reusable_pattern: bool, released: bool, released_at?, action_triggers: list[str]`

**EngineeringCompaction extends with:** `files_touched, prs_opened, tests_added, dead_end_branches, languages, frameworks`

**FrictionPoint shape:** `{category: enum[loop, tool_error, abandon, retry, deadend], description: str, turn_refs: list[turn_id]}`

**Polymorphism:** `BaseCompaction` is the parent class; role-specific extensions deferred (Sales, Design) to v2; HR indefinitely deferred

## Capture

- **v1 surfaces:** Claude Code CLI, Codex CLI; IDE collector (Cursor first) deferred to v1.5; web collector deferred to v2
- **v1 assumption:** full access to raw transcripts at known paths (`~/.claude/projects/*.jsonl`, `~/.codex/sessions/`, etc.); no permission negotiation in v1
  - *Correction (2026-06-19): on current Codex the `~/.codex/sessions/` JSONL path is stale — Codex stores SQLite and no JSONL transcripts were found on the verified machine. Claude Code (`~/.claude/projects/<slug>/<sessionId>.jsonl`, format verified against real data) is the v1 capture surface; the Codex collector is a registered stub until local sample data exists.*
- **Project inference:** `git rev-parse --show-toplevel` with cwd basename fallback; no `manthana init` required per project
- **Session boundary rule:** a session is a contiguous block of turns. New session triggered by:
  1. >30 minute gap since last turn in current session, OR
  2. Clean exit from Claude Code / Codex (Stop hook fires), OR
  3. >6 hours of continuous activity since session start (forced cap)
- **`--resume` semantics:** within the 30-minute window, extends existing session; outside the window, creates new session linked to prior via `resumed_from: session_id` reference

## Trust contract

- Employee owns the local store; org sees only what employee releases
- **Personal mode never syncs** — invariant enforced by a single dedicated test that must exist before any sync code lands
- Review-before-sync inbox surfaces every compaction with diff view before release
- `released: bool` flag on compactions; raw transcripts uploaded to object store only on explicit release (`released = true` triggers raw upload)
- K-anonymity floor on the server: no team-level aggregate produced where contributor count < 4
- Personal-mode sessions excluded from all actions, period (no opt-in carve-out in v1)

## Compactor

- Compactor invokes the engineer's existing model access, not a bundled API key:
  - **Claude Code:** shells out to `claude -p "<compaction prompt>" --output-format json`
  - **Codex:** shells out to `codex exec "<compaction prompt>"`
  - **Other surfaces (v2):** same pattern, surface-specific invocation
- Manthana ships no API key, has no hidden cost, and inherits whichever model tier the engineer has configured
- Compaction prompt is a fixed template plus the session's normalized turns serialized as compact JSON; the LLM is instructed to return a `BaseCompaction`-shaped JSON object

## Embeddings

- Local model: **`BAAI/bge-large-en-v1.5`** as default; configurable via `manthana.toml`
- All embeddings run on the engineer's laptop; no third-party embedding API in v1
- Vector store: `sqlite-vec` locally; `pgvector` server-side for cross-engineer skill clustering

## Daemon model

- Auto-start on every boot via system service:
  - **macOS:** `launchd` plist under `~/Library/LaunchAgents/com.manthana.agent.plist`
  - **Linux:** `systemd` user unit at `~/.config/systemd/user/manthana-agent.service`
  - **Windows:** Windows Service registered via `sc create`
- Daemon runs continuously; watches transcript directories with platform-native file-watchers (FSEvents on macOS, inotify on Linux, ReadDirectoryChangesW on Windows)
- No manual `manthana start` after install
- Single-binary install via `pip install manthana` triggers a post-install hook that registers the service and starts it

## Founder query

- **Structured-query-first, narrative-second:** every natural-language query is first parsed (by LLM) into a structured filter `(team?, time_range?, project?, outcome?, actor?, surface?)`, then SQL runs over compactions matching the filter, then a separate LLM call writes the narrative grounded in the SQL result
- Every claim in the narrative cites specific compaction IDs
- The grounded-citation requirement is non-optional; queries that cannot be grounded return "insufficient data" instead of hallucinating

## Test commitments

- **Personal-mode leak test** lives at `tests/test_personal_mode_invariant.py` from commit one, must pass before any sync code is merged
- Other test infrastructure (adversarial redaction suite, compaction fidelity baseline, etc.) deferred to v1.1 explicitly
- CI runs lint + type-check + the personal-mode test on every PR; broader test gates land in v1.1

## Actions

- **8 v1 actions** committed:
  1. Auto-surface prior work at session start (engineer, read, silent)
  2. Surface own forgotten solutions (engineer, read, silent)
  3. Loop detection warning (engineer, warn, opt-out)
  4. Auto-tag sessions (engineer, write, silent)
  5. Founder natural-language query (org, read, silent)
  6. Founder weekly digest (org, notify, silent)
  7. Cost transparency dashboard (engineer, notify, silent)
  8. Weekly team digest (org, notify, opt-out)
- All actions respect the consent override hierarchy (engineer opt-out wins for own data; org opt-out wins for boundary-crossing actions)
- Personal-mode sessions excluded from all actions, no carve-out

## Architectural seams (v1 must build)

These exist in v1 even though most actions are v1.5+:

- **Action dispatcher** in the local agent — component that listens for trigger events and routes to registered handlers
- **`action_triggers: list[str]` field** on every `Compaction`
- **Action queue table** on the server for pending actions awaiting human approval
- **Action audit log** for every fired action with trigger condition, confidence score, outcome
- **Consent registry** table for per-engineer and per-admin opt-in/opt-out state

## ECC reuse

- **Direct vendor** with attribution: `schemas/state-store.schema.json`, the validator pattern, cross-platform utilities (`utils.js` ported to Python), secret-detection regex patterns from `governance-capture.js`, cost-tracker token-summation logic, agent-data-home resolution pattern, session-aliases
- **Pattern reuse without direct code copy:** state-store layer (rewritten for SQLite + Postgres), session adapter system (rewritten for Manthana's flatter `Turn` schema), skill-versioning/provenance framework
- **Do NOT clone:** `continuous-learning-v2` skill (rebuild for cross-engineer mining with k-anonymity), ECC's installer (Manthana's is simpler), ECC's 262 skills/64 agents/84 command shims (irrelevant)
- **Outreach to Affaan Mustafa** on GitHub as courtesy before vendoring begins

## Naming (to confirm before first push)

- **PyPI / package name:** `manthana` (verify availability)
- **CLI binary:** `manthana` (full name; aliases `mant` or `mn` only if conflict)
- **Service name in service files:** `com.manthana.agent` (macOS), `manthana-agent` (Linux/Windows)
- **GitHub repo:** TBD (`manthana` or `manthana-platform`)
- **Environment variable for data home:** `MANTHANA_DATA_HOME`

## Open questions (not blocking v1 start)

These are catalogued but do not block the first 2,000 lines of code:

- Server authentication and multi-tenancy mechanism (likely JWT + team-scoped tokens; lock before server work begins)
- Distribution mechanism beyond `pip install` (Homebrew formula, curl one-liner)
- Design partner identification (need 2-3 startups; IIT Bombay and Actioneer networks as starting point)
- Local dashboard UI framework (FastAPI-served static HTML+HTMX recommended for v1; can swap to React in v2 if needed)
- Specific compaction prompt template (will iterate after first 20 real compactions; treat as v0 prompt to refine)
- Action versioning strategy (semver actions; defer until first action is shipped)
- Cross-org action federation (v3+; do not design for in v1)
- Engineer-level custom action authorship (security surface; defer to v3+)

---

## Order of operations for v1 build

1. **Week 1:** lock schemas in `schemas/` (Pydantic + mirrored JSON Schema); write the personal-mode invariant test against placeholder code; reach out to Affaan Mustafa
2. **Week 2:** local SQLite store + normalized `Turn` storage; cross-platform utilities ported from ECC
3. **Week 3:** `cli-collector` for Claude Code; session boundary inference; project inference
4. **Week 4:** redaction pipeline (vendoring `governance-capture.js` patterns); Work/Personal mode toggle; review-before-sync inbox
5. **Week 5-6:** compactor (shelling to `claude -p` / `codex exec`); cost tracking; local dashboard scaffold
6. **Week 7-8:** server (FastAPI), ingestion API, Postgres schema, k-anonymity floor enforcement
7. **Week 9-10:** founder structured-query-first interface; first 4 actions (auto-tag, cost dashboard, loop detection, prior-work surfacing)
8. **Week 11-12:** remaining 4 actions (founder query/digest, team digest, forgotten solutions); end-to-end deployment to one design partner
9. **Week 13-16:** harden on the design partner's real usage; iterate; prepare for second design partner

Sixteen weeks. Sequential, not parallel. One engineer.

---

## Build decisions log — session 2026-06-19 (Phase 0)

*Realized decisions from the first build session. See `manthana-architecture.md`
for the code-level mapping (file paths, schema reference, ECC reuse map).*

- **Build scope (this engagement):** Foundation + vertical slice (local side:
  capture → store → compact → view → act). No server in this engagement.
  Phase-by-phase review between phases.
- **Surfaces this build:** Claude Code first (built against real transcripts at
  `~/.claude/projects/`); Codex registered as a stub until local sample data
  exists.
- **Monorepo realized as a `uv` workspace** of four distributions sharing the
  PEP 420 namespace `manthana`: `manthana-schemas`, `manthana-collectors`,
  `manthana` (agent + CLI), `manthana-server`. Build backend `hatchling`.
  Dual-licensed: server AGPL-3.0, the rest Apache-2.0; ECC attribution in
  `NOTICE` + `LICENSES/MIT-ECC.txt`.
- **Python pinned to 3.12** via `.python-version` (packages still declare
  `>=3.11`); rationale: torch/sentence-transformers may lack 3.14 wheels, so
  embeddings will ship as an optional extra at the skill-miner phase.
- **Tenancy locked:** Org > Team > Actor, with Project as a cross-cutting tag;
  the agent authenticates to the server with a team-scoped JWT.
- **Sync chokepoint:** `manthana.agent.sync.eligible_for_sync` is the single gate
  all egress passes through; `tests/test_personal_mode_invariant.py` guards it
  from commit one (personal never syncs; release-gated; fail-closed).
- **ECC reuse approach:** clone for reference (sibling `../ecc-upstream`, outside
  the repo); copy literals verbatim with per-literal attribution
  (governance-capture secret patterns → Phase 3; cost-tracker `RATE_TABLE` →
  Phase 4); re-express patterns (agent-data-home → `agent/.../datahome.py`;
  session-adapters → `collectors/.../base.py`; state-store → Phase 1).

### Open item added — server-side LLM provider

The decisions above specify CLI-shelling (`claude -p` / `codex exec`) for the
*local* compactor only. The *server's* founder-query narrative also needs a model
but the server has no engineer Claude account. **Decision:** dev uses a mock
provider; **v1.5 the org provisions a server-side API key** behind its own
`LLMProvider` implementation. Tracked in `manthana-architecture.md` §9.
### Open item added — per-filter k-anonymity in the founder query (v1.5)

The Phase-11/founder-UI adversarial review (arch §22) flagged that `founder.py`
applies the global k-anon floor + per-project/per-outcome sub-bucket suppression,
but does not enforce a contributor floor on *every* active filter combination.
Today an `actor` filter collapses to one contributor → "insufficient", and
sub-buckets below the floor are dropped, so the practical exposure is low.
**Decision:** v1.5 adds an explicit per-filter contributor-floor check (reject /
"insufficient" if any applied filter narrows to < k-anon contributors) rather
than patching the reviewed `founder.py` in the UI pass. Tracked in arch §22.
