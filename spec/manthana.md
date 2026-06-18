# Manthana

**One-line:** Open-source platform that captures every AI interaction across an organization, extracts structured artifacts from the corpus (skills, evals, institutional memory, failure traces, cost analysis), and presents grounded visibility to founders and engineers.

## Problem

- Engineers use Claude Code, Codex CLI, Cursor, Continue, Cline, claude.ai, ChatGPT, Gemini across CLI, IDE, and web surfaces
- Each session produces work and leaves no organizational record
- Gateway tools (Helicone, Langfuse, LiteLLM, Portkey) capture only first-party API calls; they miss claude.ai and IDE usage entirely
- Enterprise governance tools (Credal, Calypso) are closed-source, top-down, and DLP-focused
- Result: organizations cannot answer "what is the team doing with AI," "where does token spend go," "what works," "what walks out when an engineer leaves"

## Architecture: four layers

### Collectors (per laptop)

- `cli-collector` watches `~/.claude/projects/*.jsonl`, `~/.codex/sessions/`, aider history, gemini-cli files
- `ide-collector` ships as extensions for Cursor, Continue, Cline, Windsurf, Copilot Chat; reads local state and SQLite
- `web-collector` ships as browser extension with content scripts and fetch/XHR interceptors for claude.ai, chatgpt.com, gemini.google.com, aistudio.google.com, perplexity.ai
- Optional local MITM proxy with org-CA for full coverage; off by default

### Local agent (runs on employee laptop)

- Stores normalized turns in local SQLite under common schema across surfaces
- Infers session boundaries from turn sequences; LLM-assisted
- Runs redaction pipeline: regex defaults (keys, emails), configurable rules, LLM-based PII scrubbing
- Tags each session Work or Personal; default Work; one-keystroke toggle
- Personal-mode sessions never leave the laptop
- Presents review-before-sync inbox showing exactly what will be released
- Presents local dashboard for employee over their own history

### Server (self-hosted by org)

- Ingestion API receives compactions; raw transcripts only on explicit release
- Postgres for compactions, S3-compatible store for raw transcripts
- Multi-tenant by team and project
- Enforces k-anonymity floor; no team-level aggregate below 4 contributors

### Extraction jobs

- **Compactor**: produces typed digest per session
- **Skill miner**: clusters compactions; proposes SKILL.md files where pattern recurs across ≥3 contributors
- **Router analyzer**: replays calls on cheaper model tiers; computes quality delta
- **Gap detector**: clusters similar queries across contributors; surfaces missing docs and tools
- **Failure miner**: tags loops, abandons, repeated retries
- **Eval generator**: converts successful sessions into eval cases tied to outcomes

## Trust contract

- Employee owns the local store; org sees only what employee releases
- Compactions flow upward by default; raw transcripts require explicit release
- Personal-mode sessions never sync
- Employee reviews diff before any sync
- Server enforces k-anonymity to prevent re-identification by inference

## Compaction object

- `BaseCompaction` fields: `session_id`, `actor`, `surface`, `project`, `duration`, `task_intent`, `approach`, `artifacts`, `outcome` (success/partial/abandoned), `friction_points`, `tier_used`, `est_cost`, `reusable_pattern?`
- `EngineeringCompaction` extends with files touched, PRs opened, tests added, dead-end branches
- `SalesCompaction` extends with prospect stage, objections raised, converting messaging, follow-ups generated
- `DesignCompaction` extends with references consulted, iteration count, decisions made, brand-consistency choices
- HR compaction deferred indefinitely on privacy and legal grounds
- Compactor invokes role-specific system prompt per type

## Outputs the org receives

- **Skills**: SKILL.md files distilled from recurring successful patterns
- **Evals**: test cases tied to real outcomes, usable to validate model swaps
- **Institutional memory**: queryable corpus of past work with citations to source sessions
- **Cost analysis**: per-task-type routing recommendations grounded in counterfactual replay
- **Failure corpus**: tagged dataset of where AI broke in real work
- **Gap signals**: missing docs and tools surfaced from aggregate friction

## Model portability

- Compactions, skills, evals, memory live above the model layer
- Org swaps models without losing accumulated artifacts
- Private evals validate whether a new model maintains task-level outcomes

## Compounding

- Mined skills improve future compaction quality
- Failure patterns improve gap-detection precision
- Evals validate skill quality
- Each cycle strengthens the next

## Founder interface

- Natural-language query: "what is the research team working on this week"
- Returns structured rollup (sessions by project, outcomes, friction, cost) plus narrative summary
- Every claim in narrative cites specific compactions
- Drill-down to released raw sessions where authorized

## License

- Server: AGPL-3.0
- Collectors, extensions, SDKs, client tooling: Apache-2.0
- Rationale: prevents SaaS competitor from re-hosting server without contributing back; keeps client tooling embeddable

## Research outputs (planned)

1. *Compaction Fidelity in Organizational AI Traces* — measurement paper; what compactions preserve vs. discard; correlation with downstream usefulness
2. *Skill Distillation from Organizational AI Traces* — method paper; whether mined skills outperform hand-written skills on real tasks
3. *Failure Modes of LLM-Assisted Work in Early-Stage Startups* — longitudinal multi-org study; first failure corpus grounded in non-contrived data

## v1 scope (months 1-4)

- `cli-collector` for Claude Code, Codex CLI, aider
- `ide-collector` for Cursor; extension scaffolding for Continue and Cline
- Local agent with SQLite, normalized turns, session inference, redaction, Work/Personal toggle, local dashboard
- Compactor producing `EngineeringCompaction`
- Self-hosted server: ingestion, multi-tenant teams/projects, k-anonymity floor
- Skill miner v0: embed + cluster + propose SKILL.md
- Founder queryable interface with grounded narrative
- 2-3 design-partner startups running it in production

## v1 excludes

- Web capture
- Sales and design role schemas
- Counterfactual router analysis
- Failure-mining UI
- Cross-org skill sharing
- Private RL environments

## Roadmap

- **v1** (months 1-4): vertical slice above
- **v2** (months 5-9): web capture, router analysis, failure-mining UI, expanded IDE coverage; submit compaction-fidelity paper
- **v3** (months 10-15): sales + design role schemas, cross-tool context continuity (Manthana becomes context layer); submit skill-distillation paper
- **v4+**: cross-org skill marketplace with opt-in publishing, model-behavior monitoring across deployments, RL training-data substrate; submit failure-modes paper

## Positioning

- **Vs. Helicone/Langfuse/LiteLLM**: captures non-API surfaces (claude.ai, IDEs, web)
- **Vs. Credal/Calypso**: open-source, local-first, employee-owned store
- **Vs. internal scripts**: structured corpus enables skill mining, eval generation, model portability

## Open questions

- Skill format: strict Anthropic SKILL.md compatibility vs. generalized superset
- Success metrics to pre-register before v1: tier-shift percentage without quality loss, skill reuse rate, onboarding time-to-productivity delta, founder-visibility score
- Data-ownership contract on the org server, separate from code license
- Design partner identification from IIT Bombay and Actioneer networks