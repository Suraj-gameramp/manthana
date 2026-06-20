"""Engineer self-query over the LOCAL store.

Two tiers:
  * ``structural_insights`` — no LLM, no tokens: rollups straight from the store
    (projects, outcomes, cost, friction, "last 7 days"). Works the moment you've
    captured sessions, before any compaction exists.
  * ``ask`` — a grounded, cited natural-language answer over your own compactions
    (every claim must cite a compaction id, or it's flagged ungrounded).

This re-expresses the server's founder-query pipeline for the single-actor local
store (no org / k-anonymity scoping — it's your own data). It deliberately does
NOT import ``manthana.server`` (that package is AGPL; this is the Apache-2.0 agent).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .cost import estimate_cost
from .llm import LLMProvider, default_provider
from .store import Store

INSUFFICIENT = "No compactions yet — run `manthana compact` first, then ask again."
_CITE_RE = re.compile(r"\[([^\]]+)\]")
_SINCE_RE = re.compile(r"^(\d+)\s*([dwh])$")  # 7d / 2w / 12h
_MAX_SCAN = 5000  # cap store reads
_COST_SCAN_CAP = 300  # cost reads turns per session; bound it (most-recent first)


@dataclass
class StructuralInsights:
    since: str | None
    session_count: int
    compaction_count: int
    by_project: dict[str, int]  # sessions per project (works without compactions)
    by_outcome: dict[str, int]  # compactions per outcome
    est_cost_usd: float
    top_friction: list[str]
    cost_capped: bool = False  # True if cost is over the most-recent _COST_SCAN_CAP only


@dataclass
class AskResult:
    narrative: str
    citations: list[str]
    grounded: bool
    filtered_to: dict[str, str] = field(default_factory=dict)


_PARSE_PROMPT = (
    "Parse this question about an engineer's OWN coding sessions into a JSON filter "
    'with keys: project, outcome (success|partial|abandoned), since ("Nd"/"Nw" or '
    "ISO date). Use null for anything unspecified. Return ONLY the JSON object.\n"
    "Question: {query}"
)
_NARRATIVE_PROMPT = (
    "Answer the engineer's question in 2-4 sentences based ONLY on this data. Cite "
    "the specific compaction id in [square brackets] for EVERY claim; do not invent "
    "facts.\nQuestion: {query}\nCompactions: {compactions}\n"
)


def _as_utc(value: datetime | None) -> datetime | None:
    # Naive datetimes are assumed UTC (the store normalizes timestamps to UTC).
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _within(started: datetime | None, cutoff: datetime | None) -> bool:
    """True if ``started`` is on/after ``cutoff`` (cutoff None = all time)."""
    if cutoff is None:
        return True
    ts = _as_utc(started)
    return ts is not None and ts >= cutoff


def _since_cutoff(since: str | None, *, now: datetime | None = None) -> datetime | None:
    """Turn '7d' / '2w' / '12h' / an ISO date into a UTC cutoff (None = all time)."""
    if not since:
        return None
    now = now or datetime.now(UTC)
    m = _SINCE_RE.match(since.strip().lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[unit]
        return now - delta
    try:
        return _as_utc(datetime.fromisoformat(since))
    except ValueError:
        return None


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return {}


def _match_citations(narrative: str, ids: list[str]) -> list[str]:
    """Map bracketed citations to compaction ids by exact-or-unique-prefix (models
    abbreviate long ids); ambiguous prefixes ground nothing. Order preserved."""
    pieces: set[str] = set()
    for token in _CITE_RE.findall(narrative):
        for part in re.split(r"[,\s]+", token.strip()):
            if part:
                pieces.add(part)
    matched = {
        hits[0]
        for piece in pieces
        if len(hits := [cid for cid in ids if cid == piece or cid.startswith(piece)]) == 1
    }
    return [cid for cid in ids if cid in matched]


def structural_insights(store: Store, *, since: str | None = None) -> StructuralInsights:
    """Token-free rollups from the local store. ``since`` accepts '7d'/'2w'/ISO."""
    cutoff = _since_cutoff(since)
    sessions = [s for s in store.list_sessions(limit=_MAX_SCAN) if _within(s.started_at, cutoff)]
    comps = [c for c in store.list_compactions(limit=_MAX_SCAN) if _within(c.started_at, cutoff)]

    by_project: dict[str, int] = defaultdict(int)
    for s in sessions:
        by_project[s.project] += 1
    by_outcome: dict[str, int] = defaultdict(int)
    friction: list[str] = []
    for c in comps:
        by_outcome[str(c.outcome)] += 1
        friction += [fp.description for fp in getattr(c, "friction_points", []) if fp.description]

    # Cost reads turns per session (an extra query each); bound it to the most
    # recent _COST_SCAN_CAP so the panel stays snappy on a large history.
    cost_sessions = sessions[:_COST_SCAN_CAP]
    cost = sum(estimate_cost(store.get_turns(s.id)).usd for s in cost_sessions)
    return StructuralInsights(
        since=since,
        session_count=len(sessions),
        compaction_count=len(comps),
        by_project=dict(sorted(by_project.items(), key=lambda kv: -kv[1])),
        by_outcome=dict(by_outcome),
        est_cost_usd=round(cost, 4),
        top_friction=friction[:5],
        cost_capped=len(sessions) > _COST_SCAN_CAP,
    )


def ask(store: Store, query: str, *, provider: LLMProvider | None = None) -> AskResult:
    """Grounded, cited NL answer over your own compactions."""
    provider = provider or default_provider()
    # 1) light NL → filter (degrade to no filter on any provider error)
    spec: dict[str, Any] = {}
    try:
        spec = _extract_json(provider.complete(_PARSE_PROMPT.format(query=query)))
    except Exception:  # noqa: BLE001 - filter parsing is best-effort
        spec = {}
    project = spec.get("project") if isinstance(spec.get("project"), str) else None
    raw_outcome = spec.get("outcome")
    outcome = raw_outcome if raw_outcome in {"success", "partial", "abandoned"} else None
    cutoff = _since_cutoff(spec.get("since") if isinstance(spec.get("since"), str) else None)

    comps = store.list_compactions(project=project, outcome=outcome, limit=_MAX_SCAN)
    comps = [c for c in comps if _within(c.started_at, cutoff)]
    filtered = {k: v for k, v in {"project": project, "outcome": outcome}.items() if v}

    if not comps:
        return AskResult(narrative=INSUFFICIENT, citations=[], grounded=False, filtered_to=filtered)

    brief = [
        {"id": c.id, "project": c.project, "intent": c.task_intent, "outcome": str(c.outcome)}
        for c in comps[:50]
    ]
    try:
        narrative = provider.complete(
            _NARRATIVE_PROMPT.format(query=query, compactions=json.dumps(brief))
        ).strip()
    except Exception:  # noqa: BLE001 - provider failure → no answer, never a crash
        return AskResult(
            narrative="Couldn't reach the model to answer.", citations=[], grounded=False,
            filtered_to=filtered,
        )
    citations = _match_citations(narrative, [c.id for c in comps])
    return AskResult(
        narrative=narrative, citations=citations, grounded=bool(citations), filtered_to=filtered
    )


__all__ = ["StructuralInsights", "AskResult", "structural_insights", "ask", "INSUFFICIENT"]
