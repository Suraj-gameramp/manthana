# Manthana — Technical Report

A curated, diagram-rich snapshot of the system: what it is, how it's built, how
data flows, the trust model, the decisions, and where it's going. (The
chronological build log lives in [`spec/manthana-architecture.md`](../../spec/manthana-architecture.md);
this report is the readable synthesis.)

## Read in this order

| # | Doc | What it covers |
|---|---|---|
| 00 | [Executive Overview](00-executive-overview.md) | 30,000-ft view: mission, the two sides, the trust contract, headline diagram |
| 01 | [System Architecture](01-system-architecture.md) | Packages, runtime components, licensing boundary, container diagram |
| 02 | [Data Pipeline & Dataflow](02-data-pipeline.md) | capture → compact → release → sync → query/skills, stage by stage |
| 03 | [Sequence Diagrams](03-sequence-diagrams.md) | The 6 key flows as Mermaid sequence diagrams |
| 04 | [Trust, Privacy & Security](04-trust-privacy-security.md) | The trust contract, egress chokepoint, redaction, k-anonymity, auth |
| 05 | [Data Model & Schemas](05-data-model.md) | Turn/Session/Compaction, the document-store pattern, store tables |
| 06 | [Deployment & Operations](06-deployment-operations.md) | Compose / image / k8s, onboarding, secrets, the ops runbook |
| 07 | [Engineering Decisions](07-engineering-decisions.md) | The locked decisions + rationale (decision → context → why → consequences) |
| 08 | [Status & Roadmap](08-status-and-roadmap.md) | Built vs deferred, test status, the next pillars (Act, Mine) |

## The system in one paragraph

Manthana is a local-first, dual-licensed platform that turns the exhaust of AI
coding sessions into **reusable team skills** and **grounded, cited founder
visibility** — under a strict **trust contract**: the employee owns the local
store, the org sees only *released + redacted + k-anonymized* data, and
personal-mode sessions never leave the laptop (enforced at one egress chokepoint,
`manthana.agent.sync.eligible_for_sync`). The employee agent (Apache-2.0) captures
Claude Code transcripts, compacts them into typed digests (reusing Claude's own
compaction summaries when present), and lets the engineer **ask** their own work
and **optimize** their Claude Code token usage; the org server (AGPL-3.0) ingests
released compactions and answers founder questions + mines cross-engineer skills.

> Diagrams use [Mermaid](https://mermaid.js.org/) and render on GitHub.
> Generated 2026-06-20; reflects the v0.2.0 line (196 tests, multiple adversarial
> reviews).
