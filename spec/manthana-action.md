# Manthana Actions Catalog

*Companion document to* `manthana-spec.md`. *The spec defines architecture; this defines capability.*

---

## Framing

Manthana captures, compacts, and queries by default. Observation alone produces dashboards. Manthana's claim is stronger: the captured corpus enables *actions* that compound across engineers, across teams, and across time. Each action either prevents waste, propagates learning, or surfaces decisions that would otherwise be invisible. Without actions, Manthana is observability software; with actions, Manthana is the substrate Nadella named — a learning loop where human capital and token capital compound.

This document catalogs every action Manthana takes (v1) or will take (v1.5+), grouped by who acts (local agent vs. org server) and what shape the action takes (read, write, warn, notify). It also specifies the consent class and confidence threshold each action requires, because actions without governance produce surveillance, not value.

---

## Action taxonomy

Every Manthana action falls into one of four shapes:

- **Read**: surface relevant information from the corpus to a person at the moment they need it. The corpus is queried; no state changes.
- **Write**: mutate state somewhere — a CLAUDE.md file, a SKILL.md in a skills repo, a GitHub issue, an eval suite, a routing config. State changes outside Manthana.
- **Warn**: detect an in-flight or imminent problem and notify the relevant person before damage compounds. Time-sensitive.
- **Notify**: send digests, summaries, or proactive distributions on a periodic or event-triggered basis. Not urgent.

Each action also has a **consent class**:

- **Silent** — local-only, engineer's own data, no notification required. Default-on.
- **Opt-out category** — engineer or admin can disable a category, but defaults apply on install.
- **Opt-in category** — disabled by default; engineer or admin explicitly enables.
- **Per-action** — explicit confirmation each time the action fires.

---

## Engineer-side actions (local agent)

The local agent acts in the engineer's interest. All engineer-side actions operate on the engineer's local corpus only; none cross the trust boundary without explicit release.

### Read actions

- **Auto-surface prior work at session start.** Trigger: new Claude Code or Codex session opened in a directory matching a project the engineer has worked in before. Action: inject 2-3 most-relevant past compactions for this project into the session opening context. Consent: silent. Confidence threshold: cosine similarity > 0.7 against compaction summaries. *v1.*

- **Surface teammate-released solutions on stuck.** Trigger: engineer hits the same tool error 3+ times within a session, or types a query semantically similar to a teammate's released compaction. Action: surface up to 2 released compactions from teammates that solved similar problems. Consent: silent (released compactions are already shared). *v1.5.*

- **Surface own forgotten solutions.** Trigger: similarity to a past compaction the engineer themselves released > 0.8. Action: notify with the past compaction inline. Consent: silent. *v1.*

- **Project-context auto-injection.** Trigger: session start in a project with accumulated lessons. Action: inject relevant prior CLAUDE.md additions and skill references at the top of the session. Consent: silent. *v1.5.*

### Write actions

- **Auto-update personal CLAUDE.md.** Trigger: compaction extracts a lesson tagged as "standing context" (e.g., "library X has bug Y in version Z"). Action: append a structured entry to the engineer's `~/.claude/CLAUDE.md` under a Manthana-managed section. Consent: opt-out category. Review queue surfaces the proposed addition before commit. *v1.5.*

- **Draft personal SKILL.md from recurring patterns.** Trigger: engineer solves the same problem class 3+ times across distinct sessions. Action: draft a `SKILL.md` file in `~/.claude/skills/personal/`, present to engineer for review and edit. Consent: opt-in category. *v1.5.*

- **Auto-tag sessions.** Trigger: every closed session. Action: write project, task type, outcome, friction tags into the local SQLite store. Consent: silent. *v1.*

- **Maintain a personal knowledge graph.** Trigger: every new compaction. Action: extract entities (files, libraries, concepts, decisions) and update a local graph linking compactions by shared entities. Consent: silent. *v2.*

### Warn actions

- **Loop detection.** Trigger: same error or same tool call repeated 3+ times within 10 minutes. Action: surface notification in local dashboard with the engineer's past solution if available, or a suggestion to escalate (ask a teammate, take a break, try a different approach). Consent: opt-out category. *v1.*

- **Tier mismatch warning.** Trigger: engineer using Opus or Sonnet on a task class where the engineer's own history shows Haiku consistently succeeds. Action: gentle notification at session end (not during the session). Consent: opt-out category. *v1.5.*

- **Contradiction warning.** Trigger: engineer about to commit code or take an action that contradicts a lesson in a past compaction (e.g., "you noted last month this approach fails because of Y"). Action: pre-commit notification with reference to the past compaction. Consent: opt-out category. *v2.*

- **Late-night quality signal.** Trigger: session activity past 10pm local time with degraded outcome signals (more retries, more abandons). Action: gentle private notification suggesting the engineer revisit fresh. Consent: opt-in category (privacy-sensitive). *v2.*

### Notify actions

- **Weekly self-recap.** Trigger: end of week. Action: generate a private digest — projects worked, friction points, what improved, cost summary. Consent: opt-out category. *v1.5.*

- **Skill suggestion digest.** Trigger: 3+ candidate skills drafted but not yet reviewed. Action: send a single notification surfacing all pending. Consent: opt-out category. *v1.5.*

- **Cost transparency.** Trigger: weekly or on-demand. Action: show per-session and per-week token spend with model tier breakdown. Consent: silent. *v1.*

---

## Org-side actions (server)

The org server acts in the organization's interest with the trust contract enforced: only released compactions are visible; k-anonymity floors prevent re-identification; sensitive actions require explicit founder or admin consent.

### Read actions

- **Founder natural-language query.** Trigger: founder query via web interface. Action: parse query into structured filter (team, time, project, outcome), run SQL over released compactions, generate narrative with citations. Consent: silent (founder is acting on their own org data, with k-anonymity floors respected). *v1.*

- **Weekly team digest.** Trigger: end of week. Action: per-team rollup — projects worked, friction points, skill adoptions, cost trends — with citations. Consent: opt-out category for the team. *v1.*

- **New-hire onboarding view.** Trigger: a new engineer joins (detected from sustained low compaction count for a new actor ID). Action: present the engineer with the team's most-used skills, the team's most-referenced past compactions, and a "what this team typically gets stuck on" digest drawn from aggregate friction. Consent: opt-out for the org. *v2.*

- **Decision archaeology.** Trigger: founder or team-lead query like "why did we decide on X?". Action: surface the original compaction(s) where the decision happened (if released). Consent: silent. *v1.5.*

### Write actions

- **Auto-draft shared org skills.** Trigger: 4+ engineers (k-anonymity floor) independently produce candidate skills clustering above a similarity threshold. Action: synthesize a single org-level `SKILL.md`, open a PR to the org's central skills repository, link evidence compactions. Consent: opt-in category at the org level; maintainer approval required to merge. *v1.5.*

- **Auto-open missing-doc GitHub issues.** Trigger: 5+ engineers query similar information not present in the org's documentation corpus. Action: open a GitHub issue with the query cluster as evidence, suggested doc location, draft answer if extractable from successful compactions. Consent: opt-in category. *v2.*

- **Auto-open broken-tool issues.** Trigger: aggregate friction signals indicate a specific tool, script, or service is causing repeated failures. Action: open a GitHub issue with linked compactions as evidence. Consent: opt-in category. *v2.*

- **Auto-generate eval cases.** Trigger: successful compactions with reusable patterns. Action: transform compaction outcomes into eval cases stored in the org's eval repository, tied to specific task classes. Consent: opt-in category, with employee opt-in required for any session contributing to evals. *v2.*

- **Auto-update routing config.** Trigger: counterfactual analysis shows a team or task class can route to a cheaper tier without quality loss (with statistical significance). Action: update the org's routing config in a PR, present evidence in the PR body. Consent: per-action — founder/admin approves each routing change. *v2.*

- **Auto-distribute solved problems.** Trigger: engineer A solves a problem; engineer B starts a similar-looking session within 2 weeks. Action: surface engineer A's released compaction to engineer B at session start. Consent: opt-in for the released-side; silent for the recipient. *v2.*

### Warn actions

- **Failure-pattern alerts.** Trigger: statistically significant spike in looped or abandoned sessions across the org or a team. Action: alert team leads with potential causes (model regression, infra issue, tool change). Consent: opt-out category for admins. *v2.*

- **Skill-drift alerts.** Trigger: an org skill's success rate (measured from skill-tagged compactions) drops below threshold week-over-week. Action: alert skill maintainer with linked failing sessions. Consent: opt-out category. *v2.*

- **Cost-anomaly alerts.** Trigger: team token spend doubles without proportional output increase, or per-engineer spend exceeds threshold. Action: alert finance lead with breakdown. Consent: opt-out category. *v1.5.*

- **Compliance and audit alerts.** Trigger: a compaction or session contains content matching configured policy violations (industry-specific — fintech, healthtech, etc.). Action: alert compliance officer with the relevant compaction; raw session available on explicit release. Consent: opt-out category for regulated orgs. *v2.*

### Notify actions

- **Founder weekly digest.** Trigger: end of week. Action: 3-5 paragraph summary of what the org accomplished with AI, where friction concentrated, recommended actions for the week ahead, all citation-grounded. Consent: silent for founder; opt-out for team-level details. *v1.*

- **Cross-team connection suggestions.** Trigger: team A solves a problem team B is currently working on (detected via compaction similarity across teams, k-anonymized). Action: notify team leads of potential knowledge transfer. Consent: opt-in category. *v2.*

- **Talent expertise mapping.** Trigger: on-demand query "who knows about X?". Action: based on success patterns in compactions, surface actual subject-matter experts (which may not match org titles). Consent: opt-in for engineers to be findable; silent for queriers. *v3.*

- **Hiring-signal digest.** Trigger: monthly. Action: based on aggregate skill gaps and recurring friction patterns, suggest what kinds of expertise the org should hire for next. Consent: opt-out for admins. *v3.*

---

## The compounding loop

The actions above are not independent. Each action either generates input for another or improves the quality of another. The compounding sequence:

1. **Engineer solves a hard problem.** Session completes with a successful outcome.
2. **Compactor produces a structured digest.** The compaction encodes task intent, approach, friction, outcome.
3. **Local agent extracts a personal skill** from recurring patterns in the engineer's compactions.
4. **Server detects similar skills across engineers** (k-anonymity floor enforced) and drafts a shared org skill via PR.
5. **Org skill merged into central skills repo.** All engineers now have it.
6. **Future engineers hitting the same problem** get the org skill auto-surfaced at session start.
7. **Their sessions are faster and cleaner,** producing higher-quality compactions.
8. **Higher-quality compactions enable richer eval cases,** which validate future model swaps with confidence.
9. **Confident model swaps mean the org can adopt cheaper or better models without quality regression,** lowering cost and improving outcomes.
10. **The substrate is now strictly better than before.** Cycle compounds.

Each loop iteration makes the next one cheaper, faster, and more accurate. This is the hill-climbing machine.

---

## v1 action commitments

v1 ships with five actions live. They are deliberately the smallest set that demonstrates Manthana as actor rather than observer, and that exercises every category of the architectural seams.

1. **Auto-surface prior work at session start** (read, silent, engineer-side)
2. **Surface own forgotten solutions** (read, silent, engineer-side)
3. **Loop detection warning** (warn, opt-out, engineer-side)
4. **Auto-tag sessions** (write, silent, engineer-side)
5. **Founder natural-language query** (read, silent, org-side)
6. **Founder weekly digest** (notify, silent, org-side)
7. **Cost transparency dashboard** (notify, silent, engineer-side)
8. **Weekly team digest** (notify, opt-out, org-side)

(Eight actions, not five — the framing "smallest set" is honest only because four of these are essentially free given the founder query infrastructure already exists.)

All other actions stage in over v1.5+ as the substrate matures and design partners provide signal on what to prioritize.

---

## Architectural seams required in v1

Most actions are v1.5+, but the v1 architecture must include seams so future actions don't require schema migrations or core refactors:

- **Action dispatcher in the local agent.** A component that registers action handlers, listens for trigger events (new compaction created, session start, error repeated), and dispatches to handlers. v1 has a handful of handlers registered; v1.5+ adds more without core changes.
- **`action_triggers` field on every Compaction.** A list of action IDs that this compaction should fire on next sync. Empty in v1 for most compactions; populated by v1.5 logic.
- **Action queue table on the server.** Pending actions awaiting human approval (auto-drafted skills, auto-opened issues, routing changes). Empty in v1.
- **Action audit log.** Every action fired by Manthana is logged with timestamp, trigger condition, confidence score, and outcome. Both for debugging and for compliance.
- **Consent registry.** Engineer-level and admin-level opt-in/opt-out state per action category. v1 has the registry table; v1.5+ adds the UI to manage it.

Without these seams in v1, every future action becomes a schema migration. With them, actions ship as new handlers registered against existing infrastructure.

---

## Action consent model

Actions without governance produce surveillance. The consent model is non-negotiable.

**Engineer-level actions:**
- Silent actions: default-on, engineer can disable via local dashboard
- Opt-out actions: default-on, engineer notified at install, can disable per-category
- Opt-in actions: default-off, engineer enables explicitly
- Per-action actions: every invocation requires explicit confirmation

**Org-level actions:**
- Founder-only actions (queries, digests): silent, founder is acting on their own org's data
- Cross-team actions (knowledge transfer, expertise mapping): opt-in per engineer to be findable
- Org-mutating actions (PRs to skills repo, GitHub issues, eval generation, routing changes): require admin approval per-action by default; can be promoted to opt-in category after track record
- Compliance/audit actions: defaults set by org based on industry; cannot be silently changed by individual engineers

**Override hierarchy:**
- Engineer's opt-out always wins over org opt-in for that engineer's own data
- Org's opt-out always wins over engineer's opt-in for actions that cross the trust boundary
- Personal-mode sessions are excluded from all actions regardless of consent state

This last point is the connection back to the trust contract from the spec: Personal sessions never contribute to any action, period. The personal-mode invariant test enforces this at code-commit time.

---

## Action confidence and failure modes

Every action has a failure mode if triggered too eagerly. The architectural commitment is that every action has a confidence threshold and a feedback loop:

- **Confidence threshold**: most actions require a measured signal above a threshold (cosine similarity > X, frequency > N occurrences, statistical significance > p). The threshold is configurable per-action per-org.
- **Feedback loop**: when an action fires, the engineer or admin can mark it "useful" or "not useful" through one click. Manthana tracks per-action usefulness rates over time. Actions with usefulness rates below a threshold are auto-suspended pending review.
- **Cooldowns**: actions of the same type for the same trigger don't fire more than once per cooldown window (default 1 hour for warns, 1 day for writes, 1 week for digest-style actions).
- **Audit visibility**: every fired action appears in the engineer's local dashboard and the org's action log, with the trigger condition and confidence score visible.

This makes actions correctable rather than authoritative. Manthana is allowed to be wrong, but it must be wrong visibly and recoverably.

---

## Open questions

A few questions remain for the actions catalog that v1 implementation will surface answers to:

- **Action versioning.** As actions evolve, how do we handle a v2 of an action when v1 is already deployed? Treat actions as semver'd modules, with deprecation and migration paths.
- **Cross-org action federation.** v3+ — if multiple orgs run Manthana, can opt-in actions share signal (anonymized failure patterns across the industry; skill marketplace contributions)? Worth designing toward, not building yet.
- **Engineer-level action authorship.** Should engineers be able to write custom actions for their own local agent? If yes, this becomes a plugin system — power but also security surface.
- **Action latency budgets.** Read actions at session-start need to complete within ~200ms or they degrade the engineer's experience. Compactor calls take longer. Write actions can run async. Latency budgets per action category should be specified before implementation.

These are catalogged but not blocking for v1.