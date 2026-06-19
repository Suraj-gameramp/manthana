"""Skill miner orchestrator: compactions → clusters → proposed SKILL.md.

v0 targets **personal** mining (the engineer's own compactions; recurrence gate =
>=N distinct sessions, 1 contributor) writing to ``~/.claude/skills/personal/``.
The same core powers **org-level** cross-engineer mining later (gate = >=4 distinct
contributors via the k-anonymity floor, ``include_contributors=False``).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from manthana.schemas import BaseCompaction

from .cluster import (
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_THRESHOLD,
    CompactionCluster,
    cluster_compactions,
    recurring,
)
from .embed import Embedder, default_embedder
from .provenance import Provenance, content_hash, make_provenance, render_provenance
from .provider import LLMProvider, SupportsRedaction
from .skillmd import SkillDraft, render_skill_md
from .synthesize import synthesize

# k-anonymity floor for org-level cross-engineer mining (decisions doc).
K_ANON_FLOOR = 4


@dataclass
class SkillProposal:
    draft: SkillDraft
    skill_md: str
    provenance: Provenance
    cluster: CompactionCluster


class SkillMiner:
    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        provider: LLMProvider | None = None,
        redactor: SupportsRedaction | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    ) -> None:
        self.embedder = embedder or default_embedder()
        self.provider = provider
        # Injected redactor (agent wires its Redactor; the server passes None —
        # its compactions are already redacted on sync). No default coupling.
        self.redactor = redactor
        self.threshold = threshold
        self.min_cluster_size = min_cluster_size

    def mine(
        self,
        compactions: Sequence[BaseCompaction],
        *,
        min_contributors: int = 1,
        min_sessions: int = 1,
        include_contributors: bool = True,
        now: datetime | None = None,
    ) -> list[SkillProposal]:
        # Privacy invariant: contributor names may only be retained for
        # single-contributor (personal) mining. Any multi-contributor mining must
        # be k-anonymized (include_contributors=False).
        if include_contributors and min_contributors > 1:
            raise ValueError(
                "include_contributors=True requires min_contributors == 1 (personal scope); "
                "multi-contributor mining must set include_contributors=False"
            )
        now = now or datetime.now(UTC)
        # Redact compaction free text BEFORE it reaches embeddings, the synthesis
        # prompt, or the skill body — so secrets/PII never enter a mined skill.
        source = (
            [self.redactor.redact_compaction(c) for c in compactions]
            if self.redactor is not None
            else list(compactions)
        )
        clusters = cluster_compactions(
            source,
            self.embedder,
            threshold=self.threshold,
            min_cluster_size=self.min_cluster_size,
        )
        proposals: list[SkillProposal] = []
        for cluster in recurring(
            clusters, min_contributors=min_contributors, min_sessions=min_sessions
        ):
            draft = synthesize(cluster, self.provider)
            skill_md = render_skill_md(draft)
            provenance = make_provenance(
                cluster, skill_md, now=now, include_contributors=include_contributors
            )
            proposals.append(SkillProposal(draft, skill_md, provenance, cluster))
        return proposals


def write_proposal(proposal: SkillProposal, skills_dir: Path | str) -> Path:
    """Write ``<skills_dir>/<name>/{SKILL.md,provenance.json}``; return the dir.

    Collision-safe: if a different skill already occupies ``<name>``, a numeric
    suffix is used (``<name>-2``…) so proposals never silently clobber each other;
    an identical existing skill (same content hash) is left as-is (idempotent).
    """
    base = Path(skills_dir)
    name = proposal.draft.name
    target = base / name
    suffix = 1
    while (target / "SKILL.md").exists():
        if content_hash((target / "SKILL.md").read_text()) == proposal.provenance.content_hash:
            return target  # identical content already written
        suffix += 1
        target = base / f"{name}-{suffix}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(proposal.skill_md)
    (target / "provenance.json").write_text(render_provenance(proposal.provenance))
    return target


def mine_org(
    compactions: Sequence[BaseCompaction],
    *,
    provider: LLMProvider | None = None,
    embedder: Embedder | None = None,
    min_contributors: int = K_ANON_FLOOR,
    now: datetime | None = None,
) -> list[SkillProposal]:
    """Cross-engineer org mining: k-anonymized (>=K_ANON_FLOOR distinct
    contributors, contributor names dropped). The safe org entry point."""
    miner = SkillMiner(embedder=embedder, provider=provider)
    return miner.mine(
        compactions,
        min_contributors=max(min_contributors, K_ANON_FLOOR),
        min_sessions=1,
        include_contributors=False,
        now=now,
    )


__all__ = [
    "SkillMiner",
    "SkillProposal",
    "write_proposal",
    "mine_org",
    "K_ANON_FLOOR",
]
