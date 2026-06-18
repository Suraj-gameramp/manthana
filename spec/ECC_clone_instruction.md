# What Manthana Can Clone From ECC

**License situation:** ECC is MIT-licensed (Copyright 2026 Affaan Mustafa). We can copy, modify, redistribute under MIT or relicense Manthana's server portion under AGPL-3.0 as long as copied files retain the original copyright notice and MIT terms. Apache-2.0 client code can incorporate MIT-licensed code freely.

Link to the repo: https://github.com/affaan-m/ecc

Below is the exhaustive list, organized by reuse tier.

---

## Tier 1: Clone directly (works as-is or near-as-is)

These solve problems Manthana would otherwise spend weeks on. Copy with attribution.

### Cross-platform utilities — `scripts/lib/utils.js` (18,132 bytes)
- File/path/process utilities tested on Windows, macOS, Linux
- Functions: `getClaudeDir`, `getSessionsDir`, `getProjectName`, `getLearnedSkillsDir`, `ensureDir`, `readFile`, `writeFile`, `appendFile`, `runCommand`, `stripAnsi`, `getDateString`, `getTimeString`, `getSessionIdShort`, `sanitizeSessionId`, `countInFile`, `log`
- TypeScript declarations in `utils.d.ts`
- **Reuse:** drop-in for Manthana's local agent

### Multi-harness data home resolution — `scripts/lib/agent-data-home.js` (200 lines)
- Resolves the local store path across Claude Code, Cursor, others
- `ECC_AGENT_DATA_HOME` environment override
- Per-project config support (`.cursor/ecc-agent-data.json`)
- Cursor hook runtime detection
- **Reuse:** rename to `MANTHANA_DATA_HOME`, otherwise drop-in

### Session ID and alias utilities — `scripts/lib/session-bridge.js`, `session-aliases.js`
- `sanitizeSessionId` for filesystem-safe IDs
- Human-readable aliases over short hashes
- **Reuse:** drop-in

### State store schema — `schemas/state-store.schema.json` (382 lines)
- JSON Schema defining: `session`, `skillRun`, `skillVersion`, `decision`, `installState`, `governanceEvent`, `workItem`
- AJV-based validator in `scripts/lib/state-store/schema.js` (94 lines)
- **Reuse:** extend with Manthana-specific `compaction` and `BaseCompaction`/`EngineeringCompaction` entities

### Hook configuration format — `schemas/hooks.schema.json` (197 lines)
- Defines Claude Code's hook config structure
- Matchers, hook types, IDs, timeouts, async flag
- **Reuse:** drop-in for any harness using Claude Code's hook protocol

### Session-end summary extraction — `scripts/hooks/session-end.js` (332 lines), specifically `extractSessionSummary`
- Reads JSONL transcript, extracts user messages, tools used, files modified
- Handles both direct and nested message.content shapes
- Counts parse errors, skips unparseable lines
- **Reuse:** this is roughly Manthana's first-pass compactor input gatherer

### Cost tracking from transcript — `scripts/hooks/cost-tracker.js` (222 lines)
- Reads JSONL transcript, sums `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` per assistant turn
- Rate table for Haiku/Sonnet/Opus
- Cumulative session totals
- Optional override from harness-cost cache file
- **Reuse:** drop-in for Manthana's per-session cost field in `BaseCompaction`

### Secret detection patterns — `scripts/hooks/governance-capture.js` (335 lines)
- Regex patterns for: AWS keys, generic secrets, private keys, JWTs, GitHub tokens
- Approval-required command patterns (force push, hard reset, rm -rf, DROP TABLE, DELETE FROM)
- Sensitive file path patterns (.env, credentials, .pem, .key, id_rsa)
- Event ID generation
- **Reuse:** this is Manthana's redaction pipeline starter kit; extend with email/phone/PII patterns

### Hook runtime controls — `scripts/lib/hook-flags.js` (~60 lines)
- `ECC_HOOK_PROFILE=minimal|standard|strict` for runtime gating
- `ECC_DISABLED_HOOKS` for selective disable
- **Reuse:** rename to `MANTHANA_*`, drop-in

---

## Tier 2: Clone the design, rewrite the implementation for Manthana's model

The architecture is sound but ECC's implementation is per-engineer and we need per-org. Copy the structure, change the semantics.

### State store layer — `scripts/lib/state-store/` (1,399 lines total)
- `index.js` (191 lines) — store API
- `schema.js` (94 lines) — entity validation
- `migrations.js` (209 lines) — schema migration framework
- `queries.js` (906 lines) — query interface
- **Adapt:** ECC's store is JSON-file based. Manthana needs SQLite for the local agent and Postgres for the org server. Keep the schema framework, swap the storage backend, add Manthana's compaction entities.

### Session adapter system — `scripts/lib/session-adapters/` (1,716 lines)
- `canonical-session.js` (644 lines) — canonical data model with validation
- `registry.js` (148 lines) — adapter registration
- `claude-history.js` (160 lines) — Claude Code adapter
- `codex-worktree.js` (355 lines) — Codex adapter
- `dmux-tmux.js` (90 lines) — dmux adapter
- `opencode.js` (319 lines) — OpenCode adapter
- **Adapt:** this is exactly Manthana's collector abstraction. ECC's canonical session is engineer-centric (worker states, orchestration); Manthana's canonical turn should be flatter. Keep the adapter registry pattern and the per-harness file structure; rewrite `canonical-*.js` for Manthana's `Turn` and `BaseCompaction` schema. The four adapters become Manthana's four collectors.

### Session manager — `scripts/lib/session-manager.js` (534 lines)
- Session CRUD (list, load, parse, stats)
- Filename pattern `YYYY-MM-DD-<short-id>-session.tmp`
- Multi-directory search (legacy + new locations)
- **Adapt:** Manthana doesn't use `.tmp` files; we use SQLite. But the CRUD interface (`getAllSessions`, `getSessionById`, `parseSessionMetadata`) is the right shape for our local agent API.

### Skill mining infrastructure — `scripts/lib/skill-evolution/` (1,053 lines) and `skill-improvement/` (374 lines)
- `tracker.js` — track skill usage and outcomes
- `provenance.js` — record what session a skill came from
- `versioning.js` — content-hashed skill versions, amendment reasons, promotion/rollback
- `health.js` — skill health metrics
- `observations.js` — collect observations of skill use
- `evaluate.js` — evaluation logic
- `amendify.js` — update existing skills
- **Adapt:** ECC mines per-engineer; Manthana mines cross-engineer with k-anonymity. Keep the provenance/versioning/health framework, replace the extraction logic with Manthana's clustering-across-contributors algorithm.

### Continuous learning hook trigger — `scripts/hooks/evaluate-session.js` (100 lines) + `observe-runner.js` (197 lines)
- Stop-hook pattern: trigger on session end, skip short sessions, signal evaluation
- Pre/post tool use observation runner
- **Adapt:** keep the Stop-hook trigger pattern, replace the inline signal with a call to Manthana's compactor pipeline.

### Hook plumbing infrastructure — `scripts/hooks/run-with-flags.js` (214 lines), `plugin-hook-bootstrap.js` (~150 lines), the inline `plugin-root resolver` in `hooks/hooks.json`
- Resolves plugin root across `~/.claude/plugins/*` layouts
- Runs hooks with profile/disable flags
- **Adapt:** Manthana needs a similar bootstrap for finding its own install path. Pattern reusable, paths need renaming.

### Pre-compact hook — `scripts/hooks/pre-compact.js` (48 lines)
- Saves state before Claude Code compacts context
- **Adapt:** Manthana wants the same trigger point to ensure compaction happens at the right boundary.

---

## Tier 3: Study, do not clone

These are useful prior art but Manthana's design diverges enough that direct reuse is the wrong move.

### Continuous-learning-v2 skill (`skills/continuous-learning-v2/`)
- Their full skill-mining pipeline: instinct capture, confidence scoring, evolution
- Files: `SKILL.md`, `hooks/observe.sh`, `agents/observer.md`, `agents/observer-loop.sh`, `agents/start-observer.sh`, `agents/session-guardian.sh`, `scripts/instinct-cli.py`, `scripts/test_parse_instinct.py`, `scripts/migrate-homunculus.sh`, `config.json`
- **Why not clone:** their algorithm is per-engineer, their "instinct" abstraction is narrower than Manthana's compaction, and their CLI is shell + Python while Manthana should be one language for the local agent. Read the algorithm, design Manthana's cross-engineer version fresh.

### Install system — `scripts/lib/install/` + `install-*.js` (~88,000 lines combined)
- Profile-based installer (`minimal`, `core`, `full`)
- Manifest-driven (`install-components.schema.json`, `install-profiles.schema.json`)
- Plan/apply pattern (`install-plan.js`, `install-apply.js`)
- Selective component install
- Doctor/repair/uninstall lifecycle
- **Why not clone:** ECC ships 262 skills + 64 agents + 84 commands across 7 harnesses; the installer's complexity reflects that. Manthana v1 ships one collector plus a local agent plus a server. A simple `npm install -g manthana-collector` and a `manthana init` command is enough. Revisit if Manthana grows the multi-component install problem.

### Worktree / orchestration — `scripts/lib/worktree-lifecycle/`, `scripts/lib/tmux-worktree-orchestrator.js` (18,241 bytes), `scripts/lib/orchestration-session.js`
- Git worktree management for parallel agent work
- tmux pane orchestration
- **Why not clone:** Manthana doesn't orchestrate work; it observes work. Different problem.

### Control pane — `scripts/lib/control-pane/` (4 files: actions.js, server.js, state.js, ui.js)
- ECC's local control-plane UI
- **Why not clone:** Manthana's local agent UI has different requirements (employee review queue, Work/Personal toggle, redaction diff). Build fresh; reading their `ui.js` is fine for inspiration.

### MCP inventory — `scripts/lib/mcp-inventory/` 
- Tracks installed MCP servers, health checks
- **Why not clone for v1:** Manthana v1 doesn't manage MCPs. Useful for v2+ if Manthana wants per-engineer MCP usage data.

### Context monitoring — `scripts/hooks/ecc-context-monitor.js` (10KB), `scripts/lib/transcript-context.js` (7KB)
- Context window monitoring and warnings
- **Why not clone:** orthogonal to Manthana's purpose; this is for the engineer, not the org.

### Quality gates — `scripts/hooks/quality-gate.js`, `pre-bash-commit-quality.js`, `stop-format-typecheck.js`, `post-edit-format.js`, `post-edit-typecheck.js`
- Code quality enforcement at hook points
- **Why not clone:** Manthana observes; it doesn't enforce. These hooks would change engineer behavior, breaking the trust contract that Manthana is a neutral observer.

---

## Tier 4: Do NOT clone

### The 262 skills (`skills/*/SKILL.md` and supporting files)
- ECC's product catalogue; specific to their use cases
- Manthana mines its own skills from real org corpus; pre-shipped skills defeat the purpose

### The 64 agents (`agents/*.md`)
- Same logic as skills

### The 84 legacy command shims (`legacy-command-shims/`)
- Deprecated even in ECC; ignore

### AgentShield (`scripts/hooks/insaits-security-monitor.py`, `insaits-security-wrapper.js`, and the separate `agentshield` repo)
- Separate product, separate scope
- Manthana's redaction borrows the patterns from `governance-capture.js` (Tier 1) but not the full AgentShield system

### ECC2 (`ecc2/` directory, Rust control-plane)
- Their alpha rewrite, unstable, separate trajectory
- Manthana is not Rust; ignore

### Dashboard GUI (`ecc_dashboard.py`)
- Tkinter desktop app
- Manthana's local dashboard should be web-based (served from local agent) for cross-platform consistency

### Specific Cursor/Codex/OpenCode/Gemini/Zed/Antigravity plugin configs (`.cursor/`, `.codex/`, `.opencode/`, `.gemini/`, `.zed/`, etc.)
- Pre-baked configs for harnesses with ECC's specific skill catalogue
- Not relevant; Manthana ships collectors, not configs

---

## Suggested v1 import order

1. **Week 1 (data model):** import `schemas/state-store.schema.json`, the validator in `scripts/lib/state-store/schema.js`, and `scripts/lib/utils.js`. Extend the schema with Manthana's `compaction` entities. This is the foundation.

2. **Week 2 (local store):** adapt `scripts/lib/state-store/` to SQLite. Keep the schema/migrations/queries pattern; swap the JSON file backend.

3. **Week 2-3 (collector):** copy `scripts/lib/session-adapters/canonical-session.js` as a template; rewrite for Manthana's flatter `Turn` schema. Copy `scripts/lib/session-adapters/claude-history.js` as the starting point for Manthana's `cli-collector`. Skip the other adapters for v1.

4. **Week 4 (capture trigger):** copy `scripts/hooks/session-end.js`'s `extractSessionSummary` and adapt for Manthana's pipeline. Use the Stop-hook trigger pattern.

5. **Week 4-5 (redaction):** copy the secret patterns and approval-command patterns from `scripts/hooks/governance-capture.js` as Manthana's redaction starter kit. Extend with email, phone, PII patterns. Add the Work/Personal toggle (no ECC equivalent).

6. **Week 5 (cost tracking):** copy `scripts/hooks/cost-tracker.js`'s rate table and transcript-summation logic. This populates `BaseCompaction.tier_used` and `est_cost`.

7. **Week 6 (data home):** copy `scripts/lib/agent-data-home.js`, rename `ECC_AGENT_DATA_HOME` to `MANTHANA_DATA_HOME`. Drop-in.

8. **Week 6-7 (compactor):** this is Manthana-specific. ECC doesn't have a compactor in our sense. Build fresh.

9. **Week 7 onwards (server, founder interface, skill miner v0):** Manthana-specific. Build fresh.

---

## Approximate engineering time saved

Conservative estimate:
- Cross-platform utilities: ~1 week saved
- State store schema and validator: ~1 week saved
- Session adapter pattern: ~2 weeks saved (vs. designing from scratch)
- Secret detection patterns: ~3-4 days saved
- Cost tracking logic: ~2-3 days saved
- Cross-harness data home resolution: ~3-4 days saved
- Stop-hook trigger pattern: ~2 days saved

**Net: roughly 4-5 weeks of v1 engineering compressed.** That cuts the 16-week v1 plan to ~11-12 weeks, or alternatively lets v1 ship with higher accuracy in the same 16 weeks.

---

## Attribution requirement

Every file copied from ECC must retain Affaan Mustafa's 2026 MIT copyright notice. Modifications must be marked. Manthana's `LICENSES/MIT-ECC.txt` should contain the full ECC MIT license. Manthana's `NOTICE` file should credit ECC for the components imported.