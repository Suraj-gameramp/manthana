"""Founder query: structured-filter-first, narrative-second (decisions doc).

Pipeline: NL query -> LLM-parsed + validated structured filter -> org-scoped SQL
over released compactions -> k-anonymity floor (global AND per sub-aggregate) ->
grounded narrative whose every claim cites compaction ids. Grounding is
non-optional: too few contributors (k-anon), or a narrative with no citations,
returns "insufficient data" rather than an ungrounded/hallucinated answer.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from manthana.schemas import Surface
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import ServerConfig
from .llm import LLMProvider
from .store import ServerStore

_log = logging.getLogger(__name__)

INSUFFICIENT = "insufficient data"
_VALID_OUTCOMES = {"success", "partial", "abandoned"}
_VALID_SURFACES = {s.value for s in Surface}
_CITE_RE = re.compile(r"\[([^\]]+)\]")


class FounderFilter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    team_id: str | None = None
    project: str | None = None
    outcome: str | None = None
    actor: str | None = None
    surface: str | None = None
    since: str | None = None  # ISO-8601
    until: str | None = None


@dataclass
class Rollup:
    session_count: int
    distinct_contributors: int
    by_project: dict[str, int]
    by_outcome: dict[str, int]
    total_cost_usd: float


@dataclass
class FounderResult:
    filter: FounderFilter
    rollup: Rollup | None
    narrative: str
    citations: list[str]
    insufficient_data: bool


_PARSE_PROMPT = (
    "Parse this founder question into a JSON filter with keys: team_id, project, "
    "outcome (success|partial|abandoned), actor, surface (claude_code|codex|cursor), "
    "since (ISO date), until (ISO date). Use null for anything unspecified. "
    "Return ONLY the JSON object.\nQuestion: {query}"
)

_NARRATIVE_PROMPT = (
    "Write a 2-4 sentence summary for a founder based ONLY on this data. Cite the "
    "specific compaction id in [square brackets] for EVERY claim; do not invent "
    "facts. If the data does not support a claim, omit it.\n"
    "Rollup: {rollup}\nCompactions: {compactions}\n"
)


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
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def parse_filter(query: str, provider: LLMProvider) -> FounderFilter:
    # A real provider (Anthropic) can raise (rate limit / network / auth); degrade
    # to an empty filter (match all) rather than 500 — and never let the raw SDK
    # exception reach the client.
    try:
        raw = provider.complete(_PARSE_PROMPT.format(query=query))
    except Exception:  # noqa: BLE001 - any provider failure degrades gracefully
        _log.exception("founder filter parse: provider call failed")
        return FounderFilter()
    data = _extract_json(raw)
    try:
        spec = FounderFilter.model_validate(data)
    except ValidationError:
        return FounderFilter()
    # Null out values that aren't valid enum members (else they silently match
    # zero rows and the founder gets a spurious "insufficient data").
    if spec.outcome is not None and spec.outcome not in _VALID_OUTCOMES:
        spec.outcome = None
    if spec.surface is not None and spec.surface not in _VALID_SURFACES:
        spec.surface = None
    return spec


def _rollup(compactions: list[Any], floor: int) -> tuple[Rollup, set[str]]:
    """Build the rollup, suppressing any project/outcome sub-bucket backed by
    fewer than ``floor`` distinct contributors. Returns the rollup and the set of
    project buckets that survived (used to gate the narrative)."""
    proj_count: dict[str, int] = defaultdict(int)
    proj_contrib: dict[str, set[str]] = defaultdict(set)
    out_count: dict[str, int] = defaultdict(int)
    out_contrib: dict[str, set[str]] = defaultdict(set)
    actors: set[str] = set()
    total = 0.0
    for c in compactions:
        proj_count[c.project] += 1
        proj_contrib[c.project].add(c.actor)
        out_count[str(c.outcome)] += 1
        out_contrib[str(c.outcome)].add(c.actor)
        actors.add(c.actor)
        total += c.est_cost_usd or 0.0

    by_project = {p: n for p, n in proj_count.items() if len(proj_contrib[p]) >= floor}
    by_outcome = {o: n for o, n in out_count.items() if len(out_contrib[o]) >= floor}
    rollup = Rollup(
        session_count=len(compactions),
        distinct_contributors=len(actors),
        by_project=by_project,
        by_outcome=by_outcome,
        total_cost_usd=round(total, 6),
    )
    return rollup, set(by_project)


def run_query(
    store: ServerStore,
    config: ServerConfig,
    *,
    org_id: str,
    query: str,
    provider: LLMProvider,
) -> FounderResult:
    spec = parse_filter(query, provider)
    compactions = store.query_compactions(
        org_id=org_id,
        team_id=spec.team_id,
        project=spec.project,
        outcome=spec.outcome,
        actor=spec.actor,
        surface=spec.surface,
        since=spec.since,
        until=spec.until,
    )
    rollup, kept_projects = _rollup(compactions, config.k_anon_floor)

    # Global k-anonymity floor.
    if rollup.distinct_contributors < config.k_anon_floor:
        return FounderResult(
            filter=spec, rollup=None, narrative=INSUFFICIENT, citations=[], insufficient_data=True
        )

    # Narrative only sees compactions whose project survived k-anon (so it cannot
    # cite a single-contributor cohort).
    visible = [c for c in compactions if c.project in kept_projects]
    brief = [
        {"id": c.id, "project": c.project, "intent": c.task_intent, "outcome": str(c.outcome)}
        for c in visible
    ]
    try:
        narrative = provider.complete(
            _NARRATIVE_PROMPT.format(
                rollup=json.dumps(rollup.__dict__), compactions=json.dumps(brief)
            )
        ).strip()
    except Exception:  # noqa: BLE001 - provider failure → withhold narrative, keep rollup
        _log.exception("founder narrative: provider call failed")
        return FounderResult(
            filter=spec, rollup=rollup, narrative=INSUFFICIENT, citations=[], insufficient_data=True
        )

    cited = set(_CITE_RE.findall(narrative))
    citations = [c.id for c in visible if c.id in cited]
    # Non-optional grounding: a narrative citing nothing is withheld (rollup kept).
    if not citations:
        return FounderResult(
            filter=spec, rollup=rollup, narrative=INSUFFICIENT, citations=[], insufficient_data=True
        )

    return FounderResult(
        filter=spec,
        rollup=rollup,
        narrative=narrative,
        citations=citations,
        insufficient_data=False,
    )


__all__ = ["FounderFilter", "Rollup", "FounderResult", "parse_filter", "run_query", "INSUFFICIENT"]
