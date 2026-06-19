"""Manthana skill miner (shared by the agent and the server).

Pipeline: embed (``embed``) → cluster + recurrence/k-anon gate (``cluster``) →
synthesize a generalized skill (``synthesize``) → validate/render the Anthropic
SKILL.md (``skillmd``) → attach provenance + content hash (``provenance``).
``SkillMiner`` orchestrates it; ``mine_org`` is the k-anonymized cross-engineer
entry point. Personal mining lives in ``manthana.agent.skillminer`` (it wires the
agent's Redactor + local store).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from .cluster import CompactionCluster, cluster_compactions, community_detection, recurring
from .embed import Embedder, HashingEmbedder, default_embedder
from .miner import K_ANON_FLOOR, SkillMiner, SkillProposal, mine_org, write_proposal
from .provenance import Provenance, make_provenance
from .provider import LLMProvider, SupportsRedaction
from .skillmd import SkillDraft, render_skill_md, validate_draft
from .synthesize import synthesize

__all__ = [
    "SkillMiner",
    "SkillProposal",
    "mine_org",
    "write_proposal",
    "K_ANON_FLOOR",
    "cluster_compactions",
    "community_detection",
    "recurring",
    "CompactionCluster",
    "Embedder",
    "HashingEmbedder",
    "default_embedder",
    "SkillDraft",
    "render_skill_md",
    "validate_draft",
    "synthesize",
    "Provenance",
    "make_provenance",
    "LLMProvider",
    "SupportsRedaction",
]
