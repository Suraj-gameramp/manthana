"""The compactor: a session + its turns -> a validated EngineeringCompaction.

The LLM provides the qualitative fields (intent, approach, outcome, friction,
artifacts, files/languages/frameworks); Manthana fills the deterministic fields
from its own data (ids, timestamps, duration, and cost/tier from the cost module
— never trusting the LLM for cost). Parsing is defensive: malformed/empty LLM
output degrades to a grounded fallback instead of crashing the pipeline.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from typing import Any

from manthana.schemas import (
    EngineeringCompaction,
    FrictionCategory,
    FrictionPoint,
    Outcome,
    Session,
    Turn,
)

from ..cost import estimate_cost
from ..llm import LLMProvider
from .prompt import PROMPT_VERSION, build_prompt


def _extract_json(raw: str) -> dict[str, Any]:
    """Best-effort parse of a JSON object from model output.

    Tries the whole string, then scans each ``{`` and uses ``raw_decode`` so
    surrounding prose or ```json fences (and stray braces in that prose) don't
    break extraction.
    """
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


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        # bool is a subclass of int — exclude it so True/False don't become strings.
        return [
            str(v) for v in value if isinstance(v, str | int | float) and not isinstance(v, bool)
        ]
    return []


def _as_outcome(value: Any) -> Outcome:
    if isinstance(value, str):
        try:
            return Outcome(value.lower())
        except ValueError:
            return Outcome.partial
    return Outcome.partial


def _as_friction(value: Any) -> list[FrictionPoint]:
    points: list[FrictionPoint] = []
    if not isinstance(value, list):
        return points
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            category = FrictionCategory(str(item.get("category", "")).lower())
        except ValueError:
            continue
        points.append(
            FrictionPoint(
                category=category,
                description=str(item.get("description", "")),
                turn_refs=_str_list(item.get("turn_refs")),
            )
        )
    return points


def _fallback_intent(turns: list[Turn]) -> str:
    for turn in turns:
        if turn.role.value == "user" and turn.content:
            return turn.content[:200]
    return "unknown"


def _duration_seconds(session: Session) -> float:
    if session.ended_at is not None:
        return max(0.0, (session.ended_at - session.started_at).total_seconds())
    return 0.0


class Compactor:
    """Produces an EngineeringCompaction from a session and its turns."""

    def __init__(self, provider: LLMProvider, prompt_version: str = PROMPT_VERSION) -> None:
        self.provider = provider
        self.prompt_version = prompt_version

    def compact(self, session: Session, turns: list[Turn]) -> EngineeringCompaction:
        raw = self.provider.complete(build_prompt(session, turns))
        data = _extract_json(raw)
        cost = estimate_cost(turns)
        return EngineeringCompaction(
            id=f"comp-{session.id}",
            session_id=session.id,
            actor=session.actor,
            surface=session.surface,
            project=session.project,
            started_at=session.started_at,
            ended_at=session.ended_at or session.started_at,
            duration_seconds=_duration_seconds(session),
            task_intent=str(data.get("task_intent") or _fallback_intent(turns)),
            approach=str(data.get("approach") or ""),
            artifacts=_str_list(data.get("artifacts")),
            outcome=_as_outcome(data.get("outcome")),
            friction_points=_as_friction(data.get("friction_points")),
            reusable_pattern=bool(data.get("reusable_pattern", False)),
            tier_used=cost.tier,
            est_cost_usd=cost.usd,
            prompt_version=self.prompt_version,
            files_touched=_str_list(data.get("files_touched")),
            prs_opened=_str_list(data.get("prs_opened")),
            tests_added=_str_list(data.get("tests_added")),
            dead_end_branches=_str_list(data.get("dead_end_branches")),
            languages=_str_list(data.get("languages")),
            frameworks=_str_list(data.get("frameworks")),
        )


__all__ = ["Compactor"]
