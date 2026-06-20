# Status and Roadmap

**Manthana v0.2.0 is foundational, team-deployable, and trust-contract-hardened. The vertical slice (capture → store → compact → view → act + sync + org mining) is complete; executor actions are the primary gap.**

---

## What is Built

### Foundation (Phases 0–3)

- **Monorepo structure** (`uv` workspace): four distributions under the PEP 420 namespace `manthana`, dual-licensed (AGPL server, Apache-2.0 client tooling).
- **Schemas** (Pydantic v2 + JSON Schema mirror): `Turn`, `Session`, `BaseCompaction`, `EngineeringCompaction`, `FrictionPoint`, `Action`, `ActionAuditEntry`, `ActionQueueItem`, `ConsentEntry` with full provenance extensions.
- **Local SQLite store** (SQLModel + versioned migrations): document-store-with-indexes pattern (index columns + authoritative JSON `data` field, round-trip validated). CRUD for sessions, turns, compactions, action audit, consent.
- **Capture pipeline** (Phases 2–3):
  - **Claude Code collector**: JSONL parse + flatten (109 verified field map), sessionization (30-min gap / 6-hour cap), project + actor inference, live on real data (209 files → 425 sessions → 28,622 turns).
  - **Redaction** (Phase 3): verbatim ECC secret-patterns + PII detection (`patterns.py` → governance-capture.js translation), Redactor (copies, not mutating), config-driven, optional LLM scrub.
  - **Work/Personal mode**: session toggle tied to the sync chokepoint (`eligible_for_sync`), enforced by `tests/test_personal_mode_invariant.py` from commit one.

### Compaction & Cost (Phase 4)

- **LLM provider abstraction**: `ClaudeCLIProvider`, `CodexCLIProvider`, `MockProvider` (deterministic for CI).
- **Cost tracking**: verbatim ECC RATE_TABLE, cost estimation (token sums → USD), tier inference.
- **Compactor**: v0 prompt serializing turns → JSON, defensive parsing (handles prose/fences), grounded fallback on malformed LLM output. Fields: deterministic (ids, duration, cost, tier) never from LLM; qualitative from model.
- **EngineeringCompaction** extends with: `files_touched`, `prs_opened`, `tests_added`, `dead_end_branches`, `languages`, `frameworks`.

### Dashboard + Auto-tag (Phase 5)

- **Action dispatcher seam**: `Dispatcher.dispatch(event)` → registered handlers, enforcing personal-exclusion (hard), consent, cooldown, confidence threshold. Full audit log (fired/suppressed/failed).
- **Auto-tag action**: the sole live v1 action (engineer/write/silent), tags sessions on close with `project`/`task_type`/`outcome`/`friction`.
- **FastAPI+HTMX dashboard** (no build step): Sessions (Work/Personal toggle + tags), Cost, Actions, Compactions (review-before-sync), Skills (SKILL.md viewer), Ask. Reuses store/cost/action/compactor/skillminer/sync modules.
- **Vertical slice verified end-to-end**: capture → store → compact → tag → view.

### Adversarial hardening (2026-06-19)

- **Agent-side review** (11 confirmed → 11 fixes): dispatcher fail-closed, sessionize boundary, idempotent re-ingest, UTC ordering, robust JSON extraction, cost tier consistency, `_str_list` bool-awareness, migration honesty, attribution rollup. Regression tests in `test_review_fixes.py`.

### Org Server + Founder Query (Phases 6–7)

- **Multi-tenant server** (SQLite dev / Postgres prod, same SQLModel): Org > Team > Actor; Project tag.
- **JWT team-scoped auth**: agent tokens (issue/verify), static admin token (founder + admin endpoints).
- **ServerStore CRUD**: tenancy, compaction ingestion, filtering, raw release to S3/MinIO/GCS/R2.
- **Founder query pipeline**: NL → LLM-parsed `FounderFilter` → org-scoped SQL → **k-anonymity floor enforcement** (distinct contributors < 4 ⇒ suppressed) → grounded narrative with compaction id citations; non-optional grounding (ungrounded claims withheld).
- **Object store abstraction**: `InMemoryObjectStore` (dev/tests), `S3ObjectStore` (MinIO/AWS/GCS/R2).
- **Server adversarial hardening** (11 confirmed → 11 fixes): cross-tenant isolation (org-namespaced PKs), cross-tenant raw upload (owned lookup), fail-closed on release (unreleased rejected at ingest), date-range off-by-a-day, per-bucket k-anonymity, atomic batch ingest, JWT `exp` requirement, filter validation, constant-time token comparison, robust citations. Regression tests in `test_server_fixes.py`.

### Agent→Server Sync (Phase 8)

- **SyncClient** (`manthana.agent.sync_client`): reads eligible compactions (personal-excluded, released-only, fail-closed via `eligible_for_sync`) → skips synced ids (idempotent) → redacts free text (redaction-on-release) → POSTs batch + raw transcripts (optional `--raw`) → records `mark_synced`.
- **Sync-state table**: migration 3, tracks pushed compactions.
- **CLI**: `manthana sync [--raw]`.
- **End-to-end verified**: capture → compact → release → sync → ingest → founder query returns grounded narrative; personal/unreleased never sync; re-sync idempotent; secrets redacted before egress.
- **Egress hardening** (5 confirmed fixes): redaction completeness (compaction + turn fields, dict keys), raw-upload sync-state (per-item isolation + separate `raw_synced_at`), verified ingest.

### Skill Miner v0 (Phases 9–10)

- **`manthana-skills` Apache-2.0 package** (shared by agent + server, input-agnostic):
  - **Embed**: `HashingEmbedder` (deterministic, offline), `SentenceTransformerEmbedder` (bge-large, optional).
  - **Cluster**: community detection (greedy, cosine threshold 0.75, k-anon gate post-hoc).
  - **Synthesize**: LLM synthesis + deterministic fallback, validate/repair (slug, reserved-word check).
  - **SKILL.md format**: verified Anthropic spec (name ≤64, slug, description ≤1024), content-hash versioning.
  - **Provenance**: source/created_at/confidence + evidence trail (compaction ids), contributor/session counts, content-hash, per-person vs k-anon redaction.
  - **Deterministic mining**: works offline/in tests, never crashes.
- **CLI**: `manthana mine-skills [--write]`, writes `~/.claude/skills/personal/{SKILL.md,provenance.json}`.
- **Miner hardening** (10 confirmed fixes): embedder hash fix (blake2b), invalid YAML (control-char strip), reserved-word slug (fixpoint removal), null-field garbage, content redaction before synthesis/embeddings, k-anon entry point, JSON extraction, write-collision suffixing, O(n²) cap (2000 items), provenance validation.
- **Org-level mining** (server): `POST /v1/admin/mine-skills {org_id}` → k-anon floor (4 contributors, names dropped) → action queue (proposal pending approval).

### Dashboard Control Plane (Phase 11)

- **Non-blocking compaction**: daemon thread, in-progress indicator, 4s refresh while in-flight.
- **Pages**: Sessions (Work/Personal), Compactions (release inbox), Skills (viewer), Cost, Actions, **Ask** (insights + grounded Q&A), **Optimize** (headroom integration).
- **Actions**: `/capture`, `/session/{id}/compact`, `/compaction/{id}/release`, `/skills/mine?threshold=`, `/sync`.
- **HTML escaping** on all rendered values, parameterized lookups, localhost single-employee.

### Founder Web Console (Phase 11)

- **Cookie-based login** (httponly): `POST /ui/login` (admin token) → `/ui/query` form.
- **Org console**: teams list, released-count, founder-query form + rollup + narrative + citations or "insufficient data", Mine org skills button.
- **UI hardening** (reviewed + fixed): auth gate (unauth → 303 redirect), wrong-token 401, console listing, query citation grounding, below-k-anon "insufficient" fallback, mine enqueue, logout-is-POST.

### Real LLM Provider (Phases 23–24)

- **`AnthropicProvider`** (server): Anthropic Messages API, optional `manthana-server[llm]` extra, text-block concat, token-params forwarding.
- **`make_provider(config)` factory**: `mock` by default (dev/tests), selectable via `MANTHANA_SERVER_LLM=anthropic`.
- **Config**: `llm_provider`, `llm_model` (default `claude-sonnet-4-6`), `llm_max_tokens` (1024).
- **Graceful degradation**: provider exceptions → empty filter / "insufficient data" in founder endpoints (no 500s).
- **Citation matching fix**: exact-or-unique-prefix matching, splits on commas/whitespace, survives model abbreviation.
- **Live verified**: real Anthropic provider yields grounded, 4-citation narrative over released+redacted org data; k-anon-surviving cohorts only.

### v1.5 Hardening (Phase 27)

- **Dev-default secret rejection**: `ServerConfig` refuses to start with shipped `_DEV_JWT_SECRET` / `_DEV_ADMIN_TOKEN` (no silent dev-mode deploy).
- **Per-filter k-anonymity** (`founder.py`): narrative visible set gated by both project AND outcome buckets surviving floor.
- **Auto-sync rate limiting**: `sync_min_interval` (60s default), throttles daemon POST frequency, `last_sync` set even on error.
- **Founder-query audit log**: `FounderQueryAuditRow`, record on both API + `/ui/query`, admin `GET /v1/admin/audit`, console panel.
- **Published image + Kubernetes**: GHCR image on version tags (`:0.2.0`), `deploy/k8s/` manifests (configmap/secret/deployment/service, non-root uid 10001, `/healthz`+`/readyz` probes), Postgres + S3 assumed external/managed.

### Team Deployment (Phase 26, Part 1–3)

- **One-command self-host**: `docker compose up` (server + Postgres + MinIO + bucket creation).
- **Dockerfile**: python:3.12-slim, `uv sync --all-packages --frozen` + extras, `/readyz` healthcheck.
- **`manthana-server onboard`**: idempotent org+team+actor creation + token minting in one step.
- **Agent onboarding**: `manthana login --server --token --actor` (writes `manthana.toml`, verifies `/healthz`), `manthana config`, `manthana sync --check`.
- **Auto-start daemon** (`manthana service install|uninstall|status`): macOS launchd (`com.manthana.watch`, RunAtLoad+KeepAlive, exports `MANTHANA_ACTOR`), Linux `systemd --user` documented.
- **Daemon auto-sync** (`manthana watch`): polls `~/.claude/projects`, ingests new/changed files (incremental, idempotent), auto-syncs released/redacted/non-personal compactions each cycle (errors logged, not fatal).
- **Watcher hardening** (7 confirmed fixes): atomic session re-ingest (one transaction), CLI closes store, `discover()` error resilience, partial-write eventual consistency.
- **Dogfood findings #1–2** (real issues from live use): re-ingest wiped compactions (fixed: `delete_compactions=False` on replace), quality validation of compactions (4.25/5 avg, faithfulness strong) + skills (2/5, overfitting; fixed: prompt edits for anti-overfit heuristics).

### Auto-capture daemon (Phase A, Part 1)

- **`manthana watch`**: stdlib polling loop, tracks `{path: mtime}`, incremental + idempotent ingest, per-file error isolation + retry, vanished-file cleanup.
- **`--compact` flag** (off by default; token-spending): runs `compact_pending` after changes.
- **Live verified**: one cycle caught up 216 files → 457 sessions → 33,348 turns on real data.
- **Tests**: `test_watcher.py` (12 tests, everything injected), 180s subprocess timeout guard.

### Engineer-side: Ask & Insights + Optimize (Phase 28)

- **`structural_insights(store, since=)`**: token-free rollups (sessions by project, outcomes, estimated cost, friction, "7d/2w/ISO").
- **`ask(store, query, provider=)`**: NL → light filter → grounded, cited answer over local compactions (exact-or-unique-prefix citations, ungrounded flagged, degrades on error).
- **`Optimize` (headroom 0.26 integration)**: context-compression wrapper (optional extra `manthana[optimize]`), maps to headroom CLI (`init claude`, `proxy`, `perf`, `learn --apply`), subprocess with injectable runner, 180s timeout, argparse validation (no shell injection).
- **Dashboard Ask + Optimize pages**, CLI commands.
- **Engineer-side hardening** (10 confirmed fixes): 180s subprocess timeout, output bounds checking (memory-DoS guard), cost scan cap (300 sessions), daemon-thread tune + logging, port validation.

### Reuse Claude's compaction summaries + cheapest-first (Phase 29)

- **Capture** (`collectors/claude_code.py`): reads newest `isCompactSummary` + `compact_boundary`, skips both from turns, `FileMeta.compact_summary`, `Session.has_compact_summary`.
- **Cheaper compaction** (`compactor/prompt.py`): feed **summary + last ~40 turns** instead of full transcript, tag `source` ("full" | "claude_summary"), `prompt_version "-summary"`.
- **Auto-compact summarized sessions** (`manthana watch --compact-summarized`, default on): cheap Claude-summary path only.
- **Cheapest-first Ask** (`insights.ask(source=)`, founder `run_query(source=)`): default includes cheap summaries, toggle on CLI/dashboard/API.
- **Org release**: summary-based compactions sync/release/redact/k-anon normally, summary content scrubbed on egress, `source` kept.
- **Proactive Optimize**: `manthana login` proactively runs `headroom init claude` (durable routing).
- **Live verified**: 5 real transcripts carry summaries (preTokens up to ~1M), adversarial review 0 actionable bugs.

### Test suite & CI

- **196 tests** across all phases: schema roundtrip, personal-mode invariant, collector/sessionize, redaction, store, compactor, cost, watcher, dashboard, server (auth/ingest/k-anon/raw/ui), skill miner, sync, team e2e, optimize, insights, and all hardening/fix regressions.
- **Adversarial review track record**: 4 reviewer rounds (agent, server, founder-UI+async, engineer-side); 60+ raw issues triaged → ~50 confirmed → 100% fixed with regressions.
- **CI workflow**: lint (ruff) + type-check (pyright) + 196-test suite.

---

## What is Deferred / Next

### Act — Agentic Actions (Next Pillar)

**Status:** Infrastructure in place; 1 of 8 v1 actions built.

- **Built:** Auto-tag (engineer/write/silent).
- **Seams present:** Dispatcher, `action_triggers` field on compactions, action audit log, consent registry, action queue.
- **Deferred (7 remaining v1 actions):**
  1. Auto-surface prior work at session start (engineer, read, silent) — search local compactions for reusable patterns.
  2. Surface own forgotten solutions (engineer, read, silent) — prompt engineer on loop-prone patterns.
  3. Loop detection warning (engineer, warn, opt-out).
  4. Founder natural-language query (org, read, silent) — **built as manual endpoint**, not auto-fired.
  5. Founder weekly digest (org, notify, silent) — time-triggered rollup.
  6. Cost transparency dashboard (engineer, notify, silent) — **built as a live page**, not pushed.
  7. Weekly team digest (org, notify, opt-out) — time-triggered org rollup.
  8. Auto-draft shared org skills (org, write, silent) — **queued in action table** pending approval.

**Path forward:** Implement handlers for actions 1–3 (engineer-side, read-only, low-friction), then 5–7 (org-side, integration with audit log + approval gate). Act is tightly coupled to Ask (1–2 search local patterns), so it pairs with pilot feedback on Ask quality over more data.

### Mine — Codebase Skill Collector (Next Pillar)

**Status:** v0 miner inputs are work-history compactions; no codebase scanner.

- **Current flow:** miner clusters work sessions → SKILL.md (what did I do); k-anon org mining identifies cross-engineer patterns.
- **Deferred:** codebase indexing + AST/embeddings to discover undocumented patterns (unused functions, recurring bugs, refactor opportunities) — input-agnostic miner can plug in codebase context once available.

**Path forward:** Design + implement a codebase "analyzer" (AST walk, embeddings on code snippets, diff mining) → feed findings to existing miner pipeline. Pairs with org adoption of mined skills in developer onboarding workflows.

### Remaining deferred items (lower priority)

- **Resume-thread stitching** — link sessions across an engineer's work (e.g., "I was debugging this MySQL issue, then switched to a feature, now back to the issue"). Multi-session narrative coherence.
- **Auto-compacting non-summarized sessions** — currently `manthana watch --compact` runs all-pending (pricier); conditional logic for heavy non-summarized sessions.
- **Auto-periodic CLAUDE.md tuning** — `manthana optimize tune` is a one-click dashboard button; can be scheduled daily/weekly.
- **Separate proxy launchd service** — headroom's durable init (`headroom init claude`) covers persistence; a dedicated service is cosmetic.
- **Per-engineer custom action authorship** (v3+) — security surface; defer indefinitely.
- **IDE collector (Cursor)** (v1.5) — Cursor surface planned; not yet integrated.
- **Web collector** (v2+) — browser-based sessions (e.g., GitHub PR review, documentation read).
- **Cross-org action federation** (v3+) — multi-org setup; do not design for v1.

---

## Known Gaps & Honest Assessment

### Quality & Coverage

- **Compaction faithfulness:** dogfood finding showed strong grounding (5/5 on 3/4 transcripts) but gaps in exact file naming, coverage-period clarity, tool/command listing, and causal reasoning. **Mitigation:** v1 prompt edits applied; further improvement requires more diverse training data + pilot feedback.
- **Skill quality vs diversity:** 3-session same-domain cluster → overfit (2/5 grade). **Root cause:** k-anon floor (≥4 contributors) requires team scale; org skills will improve with more diverse contributors. Personal mining stays limited to high-recurrence patterns.
- **Cost estimation accuracy:** token summation is grounded (from Claude's reported usage), but `tier_of(model)` is a heuristic for unknown/future models. Real spend may drift.

### Observability & Operations

- **Founder-query audit log** built (records who-asked-what, cites); no alerting on unusual access patterns. **Mitigation:** admin can review via `/v1/admin/audit`; alert logic deferred to org's own SIEM.
- **Daemon failure modes:** watcher logs errors but doesn't notify the engineer. **Mitigation:** logs written to `~/Library/Logs/manthana-watch.log` (macOS); manual review or integration with OS notifications.
- **No metrics / observability hooks:** server has no built-in metrics exporter (Prometheus/StatsD). **Mitigation:** logs are structured; metrics can be scraped from Postgres directly or added as a future layer.

### Trust & Security

- **Personal-mode invariant:** enforced locally by `eligible_for_sync` + unit test; no server-side defense-in-depth check (yet). **Current posture:** agent chokepoint sufficient (the test will catch any bypass); v1.5 tracked but not critical.
- **Redaction coverage:** compaction free-text + turn content/errors + tool input keys are scrubbed; nested structures (dict values in `tool_input`) are hit depth-first. **Gap:** if a model generates extremely adversarial output (LLM-as-tool), redaction may miss context. **Mitigation:** redaction is defense-in-depth; secrets in prompts (the primary leak vector) are caught by ECC's patterns.
- **S3 presigned URLs:** raw-release uses object store abstraction; S3 paths are not presigned (they rely on bucket policy or VPC endpoints). **Mitigation:** MinIO/S3 deployments should restrict bucket access; Kubernetes examples assume a private S3 (AWS PrivateLink or internal MinIO).
- **Config secret storage:** `manthana.toml` holds the team JWT; file is `0o600`. **Gap:** if a laptop is stolen/compromised, the token is available. **Mitigation:** tokens expire (365 days); rotation possible via re-`onboard`.

### Scalability & Performance

- **k-anonymity floor (4 contributors):** a small team (2–3 engineers) will suppress almost all org queries. **Mitigation:** this is intentional (err on privacy side); larger teams (≥5) clear the floor readily.
- **Compaction synthesis latency:** a 1M-token session → compressed ~15k-char prompt (using Claude summary) → 30–60s LLM call. **Mitigation:** non-blocking dashboard; watcher rate-limits auto-compact.
- **Skill miner latency:** 2000-item clustering + synthesis. **Mitigation:** clustering is O(n²) on cosine distance, capped at 2000; synthesis is per-cluster (1–2s each); deterministic fallback (no timeout).
- **Founder query latency:** k-anon filtering + SQL join + LLM synthesis. **Mitigation:** tests show <2s (SQLite); Postgres should be similar; LLM is 30–60s (async in the console, visible spinner).
- **Raw-transcript storage:** large sessions (1M tokens) → JSONL can be 50–100 MB. **Mitigation:** S3/MinIO handle large blobs; no issue expected at typical scale (few hundred GB per org-year).

### Model Assumptions

- **Claude as the default model:** compaction prompt tuned for Claude (Sonnet/Opus); other models not tested. **Mitigation:** the compactor is model-agnostic (shells to CLI); Codex path exists but untested.
- **Embedding model (bge-large):** skill synthesis uses embeddings; sentence-transformers is optional. **Mitigation:** HashingEmbedder (deterministic, no deps) is the default for offline/tests; ST is an optional extra.
- **English-only patterns:** SECRET_PATTERNS, PII_PATTERNS, cost-tracking (USD) all assume English + US context. **Mitigation:** redaction config is extensible; cost config is environment-driven; tracked for v2 (i18n).

### Integration Gaps

- **Headroom (Optimize):** integrated as an optional subprocess wrapper; no direct in-process compaction (architectural boundary by design). **Rationale:** keeps core lightweight, headroom changes independently.
- **IDE integration:** Cursor collector is a stub; no VS Code / Neovim support. **Rationale:** Claude Code is the v1 surface; IDE session boundaries are complex (unclear when a session ends).
- **Founder query → action feedback loop:** founder can ask "what went wrong?" but the narrative doesn't directly trigger auto-remediation (no exec actions). **Rationale:** v1 is read-only for the founder; exec actions are v2+.

---

## Architecture & Testing Philosophy

### Why this works

1. **Vertical slice first**: capture → store → compact → release → sync → query covers the full loop end-to-end, so each phase validates the layer below.
2. **Trust contract in code**: `eligible_for_sync` is the *only* egress point; `test_personal_mode_invariant.py` ensures it from commit one. No hidden channels.
3. **Adversarial review integration**: 4 multi-agent passes (agent, server, UI, engineer-side) + 100% fix rate means the system is hardened against both implementation bugs and architectural oversights.
4. **Realism grounding**: built against real Claude Code transcripts (425 sessions from the author's own work); dashboards + founder query verified live on Postgres + real Anthropic API.
5. **Decoupled packages**: AGPL server is a separate distribution; embeddings/skills are a third package; each layer can be swapped independently.

### Why gaps are acceptable

- **Actions deferred**: infrastructure is in place (dispatcher, audit, consent, queue); the 7 handlers are straightforward once data volume (sessions) reaches pilot scale.
- **Codebase mining deferred**: the miner architecture is input-agnostic; a codebase analyzer can plug in without touching `synthesize.py` or `provenance.py`.
- **IDE integration deferred**: Claude Code is the v1 surface; Cursor support is backlog.
- **Resume-thread stitching deferred**: a polish (multi-session narrative coherence); not blocking the core "what did I work on" use case.

---

## Deploying v0.2.0

### For a single engineer (laptop)

```bash
pip install manthana
manthana capture          # ingest existing sessions
manthana dashboard        # browse locally
```

### For a team (self-hosted server)

1. **Admin:** Provision the server once.
   ```bash
   docker compose up -d                    # Postgres + MinIO + server
   docker compose exec server manthana-server onboard acme "Acme Inc" platform "Platform" alice@acme.com
   ```

2. **Engineer:** One-time setup on their laptop.
   ```bash
   manthana login --server https://manthana.acme.com --token <TOKEN> --actor alice@acme.com
   manthana service install                # auto-capture + auto-sync at login
   ```

3. **Daily:** Dashboard only.
   ```bash
   manthana dashboard                      # manage Work/Personal, Compact, Release, Ask, Optimize
   ```

Raw released transcripts are synced to MinIO/S3; the founder queries via `/ui` console (structured filter → grounded narrative).

---

## Companion Docs

- **[spec/manthana-architecture.md](../spec/manthana-architecture.md)** — code-grounded architecture (file paths, schema reference, phase-by-phase breakdown, all 29 sections).
- **[spec/manthana-decisions.md](../spec/manthana-decisions.md)** — locked v1 decisions (language, storage, trust contract, actions, daemon, founder query, tests, ECC reuse).
- **[docs/deploy.md](../docs/deploy.md)** — admin guide (docker compose, secrets, TLS proxy, provisioning, Kubernetes).
- **[docs/onboarding.md](../docs/onboarding.md)** — engineer setup (one-time login, daemon auto-start, daily dashboard use).
- **[README.md](../README.md)** — quick start, repo layout, CLI commands, licensing.

---

## Version markers

- **v0.2.0 (current):** Vertical slice + team deployment + v1.5 hardening. 196 tests. Adversarial-review-hardened.
- **v1.0** (Phase C): Act (7 remaining actions), more pilot data, prompt refinements, first external design partner.
- **v1.5** (Phase D): Codebase mining, resume-thread stitching, IDE integrations, expanded action library.
- **v2.0+:** Multi-org federation, exec actions, web collector, i18n, commercial offerings.