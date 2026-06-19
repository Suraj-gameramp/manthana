"""Provenance + content-hash versioning for mined skills.

Re-expressed from affaan-m/ECC ``scripts/lib/skill-evolution/provenance.js`` (MIT,
2026 Affaan Mustafa) — a validated provenance record (source, created_at,
confidence 0..1, author) — extended for Manthana with the evidence trail
(compaction ids), contributor/session counts, cluster cohesion, and a content
hash (from the ECC state-store ``skillVersion.contentHash`` entity) for
content-addressed versioning. Written as a ``provenance.json`` sidecar next to
SKILL.md so the SKILL.md frontmatter stays portable.

Privacy: ``contributors`` (names) are included only for personal/own-data mining;
org-level cross-engineer mining passes ``include_contributors=False`` so just the
count crosses, preventing re-identification.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime

from .cluster import CompactionCluster

PROVENANCE_SOURCE = "manthana-skill-miner"


def content_hash(text: str) -> str:
    """Content-addressed version id for a SKILL.md."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Provenance:
    source: str
    created_at: str  # ISO-8601
    confidence: float  # 0..1 (cluster cohesion)
    contributor_count: int
    session_count: int
    evidence: list[str]  # compaction ids this skill was distilled from
    content_hash: str
    prompt_version: str = "v0"
    contributors: list[str] | None = None  # None for k-anonymized org-level mining


def validate_provenance(record: Provenance) -> list[str]:
    errors: list[str] = []
    if not record.source.strip():
        errors.append("source is required")
    try:
        datetime.fromisoformat(record.created_at)
    except (ValueError, TypeError):
        errors.append("created_at must be ISO-8601")
    if not (0.0 <= record.confidence <= 1.0):
        errors.append("confidence must be between 0 and 1")
    if record.contributor_count < 0 or record.session_count < 0:
        errors.append("contributor_count and session_count must be >= 0")
    if not record.evidence:
        errors.append("evidence must be non-empty")
    if not record.content_hash.startswith("sha256:"):
        errors.append("content_hash must be a sha256: digest")
    if record.contributors is not None and len(record.contributors) != record.contributor_count:
        errors.append("contributor_count must match len(contributors)")
    return errors


def make_provenance(
    cluster: CompactionCluster,
    skill_md: str,
    *,
    now: datetime,
    prompt_version: str = "v0",
    include_contributors: bool = True,
) -> Provenance:
    return Provenance(
        source=PROVENANCE_SOURCE,
        created_at=now.isoformat(),
        confidence=max(0.0, min(1.0, cluster.cohesion)),
        contributor_count=len(cluster.contributors),
        session_count=len(cluster.sessions),
        evidence=sorted(c.id for c in cluster.compactions),
        content_hash=content_hash(skill_md),
        prompt_version=prompt_version,
        contributors=sorted(cluster.contributors) if include_contributors else None,
    )


def render_provenance(record: Provenance) -> str:
    return json.dumps(asdict(record), indent=2, sort_keys=True) + "\n"


__all__ = [
    "Provenance",
    "make_provenance",
    "validate_provenance",
    "render_provenance",
    "content_hash",
    "PROVENANCE_SOURCE",
]
