# Key Engineering Decisions and Rationale

A living catalog of locked architectural choices for v1, their context, and consequences. See [`spec/manthana-decisions.md`](manthana-decisions.md) for the decision-lock and [`spec/manthana-architecture.md`](manthana-architecture.md) for code-level mapping.

---

## 1. Document store with index columns (vs. single SQLModel class)

**Decision:** Persist domain objects as JSON in a `data` column alongside typed **index columns** (for `WHERE`/`ORDER BY`), rather than one-to-one SQLModel fields.

**Context:**  
The decisions doc specified "one SQLModel class for both validation and DB," but the real constraint was:
- Keep `manthana.schemas` pure Pydantic (database-free, for JSON mirroring and cross-language reuse).
- Handle `BaseCompaction` → `EngineeringCompaction` polymorphism without a fragile ORM union or redundant field duplication.
- Avoid schema drift: if a compaction schema field changes, all 2000+ stored rows don't break.

**Rationale:**  
This pattern, re-expressed from ECC's `scripts/lib/state-store/`, cleanly separates **validation** (schemas/) from **persistence** (agent/store/). Index columns hold only what queries need (`actor`, `project`, `outcome`, `released`, `started_at`); the authoritative full object lives in `data`. Round-trip test (`test_schema_roundtrip.py`) ensures the contract and persistence never drift. Polymorphism is trivial: `CompactionAdapter.validate_python(row.data)` reconstructs the right type.

**Consequences:**
- Queries are fast (B-tree on index columns).
- Schema evolution is safe (compaction polymorphism or field additions don't break reads).
- The store layer stays decoupled from Pydantic's config (no `from_orm`, no side-effect fields).
- All four packages can share one namespace without ORM lock-in.

**Code reference:** `agent/src/manthana/agent/store/store.py` (lines 1–100); `agent/src/manthana/agent/store/tables.py`.

---

## 2. LLMProvider abstraction: local CLI shell vs. server-side SDK

**Decision:** The local compactor shells out to the engineer's own `claude` or `codex` CLI (`claude -p "<prompt>" --output-format json`); the server uses a pluggable `LLMProvider` protocol (`MockProvider` in dev, `AnthropicProvider` at runtime).

**Context:**  
Manthana ships no API key. The engineer already has Claude/Codex access on their laptop. The server has no engineer account and can't use a shared key in production. Monorepo split (AGPL server / Apache client) required de-coupling.

**Rationale:**  
- **Local agent:** Inherits the engineer's configured tier (Opus, Sonnet, free) with zero additional cost. No SDK, no secrets in the repo. Shells out to a surface-specific command (`compactor.py` → `LLMProvider.complete()` → `ClaudeCLIProvider` → `subprocess.run(['claude', '-p', prompt, '--output-format', 'json'])`).  
- **Server:** Implements `LLMProvider` locally so the AGPL server doesn't force the Anthropic SDK on Apache packages. Dev mode uses a deterministic mock (`MockProvider` returns "insufficient data"); v1.5 provisions a real org key behind `AnthropicProvider` (reads `ANTHROPIC_API_KEY` from `.env`).  
- **Both are injectable:** tests use `MockProvider` throughout; live servers pick the real provider via config (`MANTHANA_SERVER_LLM=anthropic`).

**Consequences:**
- Zero hidden costs; the engineer's bill is unchanged.
- Server can run offline (mock) or with the org's own budget.
- New surfaces (future Cursor, Aider, etc.) add a new `*CLIProvider` subclass; no SDK dependency.
- The server's narrative provider is testable without keys; real narratives are opt-in.

**Code reference:** `agent/src/manthana/agent/llm/provider.py`; `server/src/manthana/server/llm.py` (AnthropicProvider, MockProvider, make_provider).

---

## 3. Single trust-gate chokepoint: `eligible_for_sync`

**Decision:** ALL data leaving the laptop (sync, action dispatch, ingestion) passes through one function, `manthana.agent.sync.eligible_for_sync()`. Personal-mode sessions never sync—period. This invariant is enforced by a dedicated test from commit one.

**Context:**  
The trust contract is the spine: the employee owns the local store; the org sees only what is explicitly released. "Personal mode" must never leak, even on accident. One path is easier to audit than 10 scattered checks.

**Rationale:**  
- **Single gate:** `eligible_for_sync(compactions, sessions_by_id)` returns only compactions that (1) are not in a personal-mode session, (2) are explicitly `released=True`, and (3) have a resolvable session (fail closed on unknown id).  
- **Hard invariant:** `session_is_syncable(session)` returns `session.mode is not Mode.personal`—no carve-outs, no opt-in override.  
- **Tested from day one:** `tests/test_personal_mode_invariant.py` must pass before any sync transport code lands. No future phase can bypass it.  
- **Reuse:** Every future egress path (sync transport, action dispatch, founder-query prep) calls this function, not its own gate.

**Consequences:**
- All data egress is auditable at one place.
- Personal sessions are reliably safe; accidental leaks are impossible by construction.
- Refactoring is safe: any code that needs to leave the laptop must call `eligible_for_sync` first.
- The test suite is non-negotiable: CI rejects any PR that breaks it.

**Code reference:** `agent/src/manthana/agent/sync.py`; `tests/test_personal_mode_invariant.py`.

---

## 4. K-anonymity floor (≥4) + drop names + per-filter enforcement

**Decision:** No team-level aggregate is produced where the distinct contributor count is <4 (global floor). Sub-aggregates (by project, by outcome, per applied filter) also apply the floor. On org-level skill mining, contributor names are dropped. Personal mining includes names.

**Context:**  
Manthana mines team skills from released compactions. A skill mined by 2 people is a personal hack; by 4+, it's reusable team knowledge. A founder query filtered to one actor shouldn't accidentally reveal that actor's personal work.

**Rationale:**  
- **K-anonymity ≥4 is a standard** in privacy (US Census, HIPAA, etc.) and is defensible in practice.  
- **Global + per-sub-aggregate:** A query might pass the global floor but collapse to 1 contributor when filtered by project. The narrative only surfaces cohorts that survive the floor on **both** dimensions.  
- **Drop names on org skills:** The mined skill description (procedure, trigger pattern) is valuable; "this was built by person X" is not. Names are dropped; counts are kept for audit.  
- **Per-filter check (v1.5):** The founder-query narrative is now gated by contributor floor on every active filter (`actor`, `project`, `outcome`, `surface`, `since`/`until`), preventing a narrow query from narrowing into sub-k-anon, then grounding to one person's work.

**Consequences:**
- Skills are shared team knowledge, not personal hacks.
- Founder queries never expose sub-floor cohorts, even filtered.
- The org respects the k-anon floor; deanonymization is hard.
- Personal insights (engineer running `manthana insights`) show all data; org dashboards suppress sub-floor rollups.

**Code reference:** `server/src/manthana/server/founder.py` (k-anon checks, narrative suppression); `skills/src/manthana/skills/miner.py` (`mine_org` hardcodes `K_ANON_FLOOR=4`, drops names).

---

## 5. Redaction-on-release: ECC patterns + literal copying, per-literal attribution

**Decision:** Copy the ECC `governance-capture.js` secret-detection patterns **verbatim** (SECRET_PATTERNS, APPROVAL_COMMANDS, SENSITIVE_PATHS) with per-literal attribution. Redact free-text fields (task intent, approach, artifacts, error stacks, tool-input keys) before release/sync; keep full fidelity locally.

**Context:**  
The redaction patterns are battle-hardened from production ECC sessions. Re-inventing them risks missing secret families (AWS keys, Slack tokens, database URLs). ECC is MIT-licensed; vendoring with attribution is clean.

**Rationale:**  
- **Verbatim copy:** The patterns are field-tested; translating them to Python risks bugs. JS source is preserved in comments; NOTICE credits the source.  
- **Per-literal attribution:** Each pattern has a link to the original ECC file (e.g., `# from affaan-m/ecc::scripts/hooks/governance-capture.js`).  
- **Redaction path:** Local store keeps full fidelity (trust the engineer). Redaction applies on the path to release: `Redactor.redact_compaction()` returns a copy with secrets scrubbed, ready for sync/upload. A turn's `error` field (stack traces echo secrets) and dict keys in `tool_input` are also scrubbed.  
- **PII patterns:** Email, phone added (Manthana-specific), validated against real data.  
- **Optional LLM scrub:** An `llm_scrub` hook (off by default) can detect context-specific secrets; cost is optional.

**Consequences:**
- Secrets are reliably hidden before egress; leaks are rare.
- Local analysis uses full context (unredacted); org gets sanitized shared knowledge.
- Patterns are proven in the field; new patterns are incremental.
- Redaction is non-destructive locally (store keeps originals); re-release with updated patterns is safe.

**Code reference:** `agent/src/manthana/agent/redaction/patterns.py` (SECRET_PATTERNS, etc., with ECC source links); `agent/src/manthana/agent/redaction/redactor.py` (`redact_text`, `redact_compaction`, `redact_turn`).

---

## 6. ECC reuse approach: copy literals, re-express patterns, clone for reference

**Decision:** (1) Verbatim copy of constants/patterns (SECRET_PATTERNS, RATE_TABLE) with per-literal attribution. (2) Re-express algorithms/subsystems in idiomatic Python (session-adapters → base.py, state-store → SQLite store). (3) Clone the full ECC repo locally (`../ecc-upstream`) for reference; do not import it as a dependency.

**Context:**  
ECC is a 262-skill, 84-agent platform built by Affaan Mustafa. Manthana is orthogonal (cross-engineer work capture) but reuses proven patterns. Mixing MIT + Apache + AGPL requires care.

**Rationale:**  
- **Verbatim constants:** RATE_TABLE (token pricing), SECRET_PATTERNS (regex), APPROVAL_COMMANDS are exact; translating them risks deviation from battle-tested rules.  
- **Re-express patterns:** State management (agent-data-home), session boundaries (session-end.js), skill provenance frameworks are *ideas*, not code. Rewrite them in Manthana's architecture; cite the inspiration.  
- **Never import ECC:** ECC's CLI, skill system, and command shims are not Manthana's responsibility. Cloning it locally (sibling dir) lets engineers learn from it without a runtime dependency.  
- **Outreach:** GitHub courtesy to Affaan Mustafa before vendoring begins.

**Consequences:**
- Manthana is independent and installable without ECC.
- Proven patterns are reused; new code is Manthana's.
- Attribution is clear (NOTICE + `LICENSES/MIT-ECC.txt`).
- Future ECC updates are manual ports (safe, auditable).

**Code reference:** `NOTICE`, `LICENSES/MIT-ECC.txt`; per-file headers (e.g., `agent/src/manthana/agent/store/store.py` line 3–5).

---

## 7. Headroom integration: reference-only → optional direct → proactive setup

**Decision:** Headroom (context-compression layer, Apache-2.0, Affaan Mustafa) is cloned locally for reference. The Optimize feature integrates it as an **optional extra** (`manthana[optimize]` → `headroom-ai[proxy,mcp]`). `manthana login` proactively runs `headroom init claude` when headroom is installed.

**Context:**  
Manthana captures work; headroom compresses LLM calls. Together, they let the engineer run Claude Code more efficiently. Headroom is orthogonal (not owned by Manthana); Manthana supplies the real history to tune from, and headroom supplies the compression.

**Rationale:**  
- **Reference, not vendored:** Headroom is a separate tool with its own distribution. Clone it locally so Manthana engineers can study its compression techniques; don't embed it.  
- **Optional extra:** Not everyone needs compression; don't force `torch` + sentence-transformers on the core. `manthana[optimize]` includes `headroom-ai[proxy,mcp]`; without it, the CLI degrades to an install hint.  
- **Proactive setup:** `manthana login` checks if headroom is installed and auto-runs `headroom init claude` (durable routing), reducing friction. `--no-optimize` skips it.  
- **Dashboard integration:** The Optimize page has one-click "Wire Claude Code through headroom" (setup) + proxy status + perf stats + `learn --apply` to tune CLAUDE.md.

**Consequences:**
- Headroom's compression is available to users who want it; others are unaffected.
- Manthana supplies the history; headroom supplies the compression.
- The integration is shallow (subprocess calls, injectable runner), so Manthana doesn't become a Rust/build-dependency burden.
- Differentiation: Manthana is work capture + grounded-citation engine + optional compression, not just a compressor.

**Code reference:** `agent/src/manthana/agent/optimize.py` (subprocess runner, headroom CLI integration); `agent/src/manthana/config.py` (proactive init); dashboard Optimize page.

---

## 8. Reuse Claude's compaction summaries + cheapest-first Ask + auto-compact summarized-only

**Decision:** Claude Code auto-compacts heavy sessions, capturing a `isCompactSummary` + `compact_boundary` meta. Manthana reuses the summary (feed summary + last ~40 turns, not the full transcript) so compaction is cheap. Ask defaults to the cheapest digest (summary-derived compactions); a toggle switches to "full only." Auto-compaction defaults to summarized-only (`--compact-summarized`), skipping expensive full re-compaction.

**Context:**  
Real sessions in user data: ~5 carry summaries. One had `preTokens ~1,004,684` (1M tokens). Asking Manthana to re-summarize that is wasteful; Claude already did the work.

**Rationale:**  
- **Capture the summary:** `ClaudeCodeCollector.read()` scans for the newest `isCompactSummary` + `compact_boundary` meta and **skips both from turns** (no duplicate 1M-token line). FileMeta and Session track the presence.  
- **Build cheaper prompt:** `compactor/prompt.py` feeds summary + recent turns (not the full transcript) to the LLM. Compactions carry a `source` field ("full" | "claude_summary").  
- **Auto-compact summarized:** `manthana watch --compact-summarized` (default on) compacts only flagged sessions. `--compact` does all pending (pricier). The watcher auto-syncs each cycle if configured.  
- **Cheapest-first Ask:** `manthana ask` defaults to both summary-derived + full compactions. A `--source full` toggle excludes cheap summaries. Dashboard and founder console have the same toggle.  
- **Org release:** Summary-based compactions are ordinary compactions → sync/redact/k-anon apply. The `source` field is preserved (in `_COMPACTION_KEEP`); summary-derived content is scrubbed on egress so the org gets the redacted full compaction.

**Consequences:**
- Large sessions compact for ~1/10 the cost.
- Engineer can ask faster over cheap summaries; toggle to full-only for precision.
- Daemon runs cheap auto-compaction; expensive full-compaction is a dashboard button.
- Work capture scales to real sessions without token overspend.

**Code reference:** `collectors/src/manthana/collectors/claude_code.py` (capture summary + compact_boundary); `agent/src/manthana/agent/compactor/prompt.py` (build_prompt w/ summary); `agent/src/manthana/agent/watcher.py` (auto-sync + compact_pending); `agent/src/manthana/insights.py` (ask source toggle).

---

## 9. Server-side LLM provider (open item, v1.5)

**Decision:** Dev/tests use a deterministic mock. v1.5 provisions the org with a server-side API key behind the `LLMProvider` protocol.

**Context:**  
The server generates founder narratives. The server has no engineer account and can't use a shared key. A real provider is optional for dev; v1 ships with mock + graceful degradation.

**Rationale:**  
- **Mock in dev:** No key required. Founder queries return "insufficient data" deterministically. Tests pass without secrets.  
- **Real provider in v1.5:** Org provisions an API key; `AnthropicProvider` reads it from `ANTHROPIC_API_KEY`. Config: `MANTHANA_SERVER_LLM=anthropic MANTHANA_SERVER_LLM_MODEL=claude-sonnet-4-6`.  
- **Graceful degradation:** If the provider raises (rate-limit, network, auth), both `parse` and `narrative` calls are wrapped. Parse failure → empty filter (match all); narrative failure → "insufficient data". Errors are logged, never surfaced to the client.  
- **Citation matching fix:** Real models abbreviate long UUID ids and group them in brackets. `_match_citations` now splits each bracket on commas/whitespace and matches by exact-or-unique-prefix—ambiguous prefixes ground nothing, so grounding never reaches the wrong compaction.

**Consequences:**
- v1 is fully functional with mock narratives.
- v1.5 adds real grounded narratives without re-architecting the server.
- Provider exceptions don't crash the console; fallback is clean.
- Citation matching is robust to model quirks (abbreviation, grouping).

**Code reference:** `server/src/manthana/server/llm.py` (AnthropicProvider, MockProvider, make_provider); `server/src/manthana/server/config.py` (llm_provider, llm_model, llm_max_tokens); `server/src/manthana/server/founder.py` (_match_citations, exception handling).

---

## 10. Adversarial-review-after-every-phase hardening

**Decision:** After each major phase (capture, redaction, compactor, server, sync, skills, dashboard, deploy), a 2–4 reviewer adversarial pass identifies real and speculative bugs. Fixes are merged with regression tests before the next phase starts.

**Context:**  
Single-engineer build. Mistakes compound. Human reviewers catch bugs the builder misses. A deliberate formal pass keeps quality high.

**Rationale:**  
- **Multi-agent review:** 4–21 agents per phase, seeded with skeptical personas (attacker, formal-methods critic, tester, user). Each finds issues independently, then a triage step merges duplicates and confirms real bugs.  
- **Fixes + regressions:** Every fix adds a regression test. Test suite grows; future changes break the fix? CI catches it.  
- **Tracking:** Deferred items (low-priority, v1.5) are logged in the architecture doc, not lost.  
- **Example wins:** Found actor-spoofing in auth (one token could spoof 4 actors), daemon-thread async-completion failure logging, empty-secret auth bypass, per-filter k-anon narrowing, citation-matching abbreviation handling, idempotent re-ingest wiping compactions.

**Consequences:**
- Real security/logic bugs are found and fixed before a design partner sees them.
- Test coverage is always growing (61 → 75 → 131 → 185+ tests through phases).
- The codebase is defended from obvious mistakes.
- Deferred v1.5 work is tracked (audit log, per-filter k-anon, dev-default secret rejection, etc.).

**Code reference:** `tests/` directory (test_review_fixes.py, test_server_fixes.py, test_skillminer.py); architecture doc phases 11, 13, 17, 22, 27 review sections.

---

## 11. AGPL server / Apache client split (licensing)

**Decision:** The local agent (capture, store, compactor, dashboard, sync client) is Apache-2.0. The server (ingestion, founder query, UI, org mining) is AGPL-3.0. Schemas and collectors are shared (Apache).

**Context:**  
The server is the org's proprietary infrastructure; the agent is the engineer's laptop. If a company forks the server, they must release their changes. If they fork the agent, they only owe attribution. Different incentives, different licenses.

**Rationale:**  
- **Apache agent:** Free/proprietary/internal forks are all OK; no obligation to share improvements. Companies can fork the agent to add custom collectors or dashboards without license trouble.  
- **AGPL server:** If you run the server, you must release your deployment (code, configs). This ensures the org's work-capture infrastructure stays open; companies can't lock users into a proprietary version.  
- **Schemas/collectors:** Shared Apache-2.0, so any package can import them. Collectors are reusable (Cursor, Aider, Codeium plugins can link to `manthana-collectors`).  
- **Four distributions:** `manthana-schemas` (Apache), `manthana-collectors` (Apache), `manthana` (Apache), `manthana-server` (AGPL), but one PEP 420 namespace so imports work seamlessly.

**Consequences:**
- Enterprises can deploy confidently (AGPL guarantees openness).
- Individuals and small teams can fork the agent with minimal compliance burden.
- The ecosystem can build on schemas and collectors without license friction.
- Contributors know their work will stay open if vendored by others.

**Code reference:** `LICENSE`, `pyproject.toml` (each package's license field), `NOTICE`, `LICENSES/Apache-2.0.txt`, `LICENSES/AGPL-3.0.txt`.

---

## 12. SQLite local + Postgres server (with optional sqlite-vec → pgvector)

**Decision:** The local agent uses SQLite (single file, no setup). The server uses Postgres in production (managed or self-hosted). Both support optional vector indexes: `sqlite-vec` locally (clustering during skill mining), `pgvector` server-side (skill miner cross-engineer, post-v1).

**Context:**  
SQLite is frictionless for the engineer's laptop. Postgres scales to the org. Both can use the same SQLModel table definitions; migrations apply to either backend.

**Rationale:**  
- **SQLite locally:** No daemon, no configuration, single file at `$MANTHANA_DATA_HOME/manthana.db`. Multi-process safety via WAL + `PRAGMA busy_timeout=5000`. Journaling, backups, and destruction are filesystem operations.  
- **Postgres server:** Handles multi-tenant queries, connection pooling, and backups. Same SQLModel models; same migrations. Dev can use SQLite; prod uses Postgres.  
- **Vector indexes:** Optional. Locally, `sqlite-vec` (via setup.py extra) enables fast cosine clustering for skill mining. Server-side, `pgvector` (v1.5) enables cross-engineer mining (finding similar compactions from different people). Both are opt-in (tests use in-memory defaults).

**Consequences:**
- The engineer installs Manthana and it works offline (no database setup).
- The org deploys the server to Postgres and gets multi-tenancy.
- Migrations are version-controlled and idempotent across both backends.
- Vector search is available when installed; absent if not.

**Code reference:** `agent/src/manthana/agent/store/engine.py` (SQLite creation, pragmas, optional sqlite-vec); `server/src/manthana/server/db.py` (Postgres engine, StaticPool for tests); migrations in `agent/src/manthana/agent/store/migrations.py`.

---

## 13. Daemon auto-sync (watcher) with capture-optional toggle

**Decision:** `manthana watch` runs continuously, polling `~/.claude/projects` every N seconds. It ingests new/changed transcripts incrementally. If a server is configured, each cycle also syncs (pushes released/redacted compactions). `--no-sync` disables; failures don't kill the loop.

**Context:**  
The founder's vision: hand over a laptop, set it up once, then it runs itself. The engineer only touches the dashboard. The daemon handles capture, auto-compaction (cheap, summarized-only by default), and auto-sync.

**Rationale:**  
- **Polling (not inotify):** Portable (macOS/Linux/Windows via stdlib); filesystem-watch edge cases (permissions, symlinks, lazy-loaded cloud drives) are avoided. Polling every 10s is fast enough for real-time feel.  
- **Incremental:** Track `{path: mtime}` and ingest only new/changed files. First cycle catches up; later cycles are fast.  
- **Atomic re-ingest:** If a file changes (e.g., Claude Code appends more turns), `Store.replace_session_family` deletes the old sessions and re-inserts the new ones **in one transaction**. Concurrent reads (dashboard compaction thread) never see a mid-delete state.  
- **Auto-sync:** Each cycle, after ingest, push released compactions to the server (if configured). Sync failures are logged and skipped; the loop continues.  
- **Auto-compact (cheap):** By default (`--compact-summarized`), auto-compact only sessions that Claude summarized (cheap, ~1/10 cost). `--compact` does all pending (pricier); neither is forced (compaction is expensive and manual in the dashboard).

**Consequences:**
- The engineer sets it up once (`manthana login`, `manthana service install`) and forgets about it.
- Transcripts are captured automatically; the dashboard always has fresh data.
- Auto-sync keeps the org's data current (manual release is still a dashboard button).
- Failures don't cascade; the daemon retries next cycle.

**Code reference:** `agent/src/manthana/agent/watcher.py` (watch loop, incremental ingest, sync each cycle); `agent/src/manthana/agent/sync_client.py` (SyncClient, eligible_for_sync); `agent/src/manthana/agent/cli.py` (`manthana watch`).

---

## 14. Trusted local agent, untrusted org server (secrets in .env, not CLI)

**Decision:** Secrets (`MANTHANA_SERVER_JWT_SECRET`, `MANTHANA_SERVER_ADMIN_TOKEN`, `ANTHROPIC_API_KEY`) live in a gitignored `.env` file, never on the command line or in config files. `scripts/serve.sh` sources the `.env` before running the server.

**Context:**  
An API key pasted into a CLI command leaks into shell history (`~/.bash_history`), process lists (`ps aux`), and logs. If the history or logs are shared or cached (GitHub transcript, Slack screenshot), the key is compromised.

**Rationale:**  
- **Environment variables:** `.env` is gitignored; `scripts/serve.sh` does `set -a; source .env; set +a` (exports all vars) before running the server. Env vars don't appear in `ps` (they're inherited, not argv).  
- **Template tracking:** `.env.example` is committed (negated `.gitignore` with `!.env.example`) so deployments know what secrets are needed.  
- **No shell invocation:** The runner is Python directly (not `bash -c`), so argv is protected.  
- **Rotation reminder:** If a key ever lands on a command line or in a shared transcript, rotate it at console.anthropic.com.

**Consequences:**
- Secrets are confined to a single file, readable only by the owner (file perms `0o600`).
- Deployments are safe: `docker compose up` reads secrets from `.env`; the image never embeds them.
- Leak surface is minimized.
- Auditable: review the source of every secret (always `.env`, never config).

**Code reference:** `scripts/serve.sh`; `.env.example`; `server/src/manthana/server/config.py` (env var loading).

---

## Conclusion

These decisions form a coherent system: **trust the engineer locally (full fidelity, personal-mode hard-gated), trust the org minimally (released+redacted+k-anon data only), audit everything (sync chokepoint, adversarial review, audit logs).** The codebase enforces the contract through tests (personal-mode invariant from day one), deployable patterns (docker-compose, launchd, systemd), and iterative hardening (review fixes after every phase).

See [`spec/manthana-architecture.md`](manthana-architecture.md) for code-level mapping and [`spec/manthana-decisions.md`](manthana-decisions.md) for locked decisions by phase.