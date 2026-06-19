"""Clustering compactions into recurring task-pattern clusters.

Uses the sentence-transformers "fast clustering" / community-detection algorithm
(greedy, non-overlapping, unknown-k): for each point gather all points within a
cosine threshold; keep communities above a minimum size; take largest-first,
removing already-assigned points. k-means is deliberately avoided (fixed k).

The k-anonymity / recurrence gate (>=N distinct contributors or sessions) is
applied AFTER clustering, on cluster membership — so 10 sessions from one person
do NOT qualify as a shared pattern.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from manthana.schemas import BaseCompaction

from .embed import Embedder, Vector, cosine

DEFAULT_THRESHOLD = 0.75  # SBERT community_detection default cosine cutoff
DEFAULT_MIN_CLUSTER_SIZE = 2  # a "pattern" needs at least two occurrences


def community_detection(
    embeddings: list[Vector],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_community_size: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> list[list[int]]:
    """Greedy non-overlapping communities (SBERT-style). Returns index lists."""
    n = len(embeddings)
    sims = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = 1.0 if i == j else cosine(embeddings[i], embeddings[j])
            sims[i][j] = sims[j][i] = s

    candidates: list[set[int]] = []
    for i in range(n):
        members = {j for j in range(n) if sims[i][j] >= threshold}
        if len(members) >= min_community_size:
            candidates.append(members)
    candidates.sort(key=len, reverse=True)

    result: list[list[int]] = []
    assigned: set[int] = set()
    for members in candidates:
        fresh = members - assigned
        if len(fresh) >= min_community_size:
            result.append(sorted(fresh))
            assigned |= fresh
    return result


def _cohesion(embeddings: list[Vector], indices: list[int]) -> float:
    """Mean pairwise cosine within a cluster (a confidence signal)."""
    pairs = [
        cosine(embeddings[a], embeddings[b])
        for ai, a in enumerate(indices)
        for b in indices[ai + 1 :]
    ]
    return round(sum(pairs) / len(pairs), 4) if pairs else 1.0


@dataclass
class CompactionCluster:
    compactions: list[BaseCompaction]
    cohesion: float
    contributors: set[str] = field(default_factory=set)
    sessions: set[str] = field(default_factory=set)

    @property
    def size(self) -> int:
        return len(self.compactions)


def default_text_of(compaction: BaseCompaction) -> str:
    """The semantic content used for embedding a compaction."""
    return f"{compaction.task_intent} {compaction.approach}".strip()


DEFAULT_MAX_ITEMS = 2000  # community_detection is O(n^2); cap to bound time/memory


def cluster_compactions(
    compactions: Sequence[BaseCompaction],
    embedder: Embedder,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    max_items: int = DEFAULT_MAX_ITEMS,
    text_of: Callable[[BaseCompaction], str] = default_text_of,
) -> list[CompactionCluster]:
    if not compactions:
        return []
    # community_detection builds a dense n*n similarity matrix; cap n so a huge
    # store can't OOM/hang. Inputs are most-recent-first, so we keep the newest.
    items = list(compactions)[:max_items]
    embeddings = embedder.embed([text_of(c) for c in items])
    clusters: list[CompactionCluster] = []
    for indices in community_detection(
        embeddings, threshold=threshold, min_community_size=min_cluster_size
    ):
        members = [items[i] for i in indices]
        clusters.append(
            CompactionCluster(
                compactions=members,
                cohesion=_cohesion(embeddings, indices),
                contributors={c.actor for c in members},
                sessions={c.session_id for c in members},
            )
        )
    return clusters


def recurring(
    clusters: list[CompactionCluster],
    *,
    min_contributors: int = 1,
    min_sessions: int = 1,
) -> list[CompactionCluster]:
    """Keep only clusters that meet the recurrence / k-anonymity floor."""
    return [
        c
        for c in clusters
        if len(c.contributors) >= min_contributors and len(c.sessions) >= min_sessions
    ]


__all__ = [
    "community_detection",
    "cluster_compactions",
    "recurring",
    "CompactionCluster",
    "default_text_of",
    "DEFAULT_THRESHOLD",
    "DEFAULT_MIN_CLUSTER_SIZE",
]
