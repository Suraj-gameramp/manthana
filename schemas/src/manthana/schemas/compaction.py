"""Compaction objects — the typed digest produced per session.

``BaseCompaction`` is the parent; ``EngineeringCompaction`` extends it for v1.
Sales/Design role schemas are deferred to v2; HR is deferred indefinitely
(decisions doc). The two are joined into a discriminated union keyed on ``kind``
so a stream of mixed compactions deserializes to the right subclass.

The ``BaseCompaction`` field set follows the decisions doc verbatim, plus a few
documented Manthana extensions (``id``, ``kind``, ``prompt_version``,
``schema_version``, ``created_at``) needed to store, version, and route them.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .enums import Outcome, Surface
from .friction import FrictionPoint


class BaseCompaction(BaseModel):
    """Typed digest of a single session (surface-agnostic)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["base"] = "base"

    id: str = Field(..., description="Stable compaction id")
    session_id: str
    actor: str
    surface: Surface
    project: str

    started_at: datetime
    ended_at: datetime
    duration_seconds: float

    task_intent: str = Field(..., description="What the engineer set out to do")
    approach: str = Field(..., description="How they went about it")
    artifacts: list[str] = Field(default_factory=list, description="Things produced")
    outcome: Outcome
    friction_points: list[FrictionPoint] = Field(default_factory=list)

    tier_used: str | None = Field(default=None, description="Dominant model tier")
    est_cost_usd: float | None = None
    reusable_pattern: bool = False

    # Trust contract: compactions flow up by default once released; raw
    # transcripts upload only when released is set true.
    released: bool = False
    released_at: datetime | None = None

    # Architectural seam: action ids this compaction should fire on next sync.
    action_triggers: list[str] = Field(default_factory=list)

    # Documented Manthana extensions.
    prompt_version: str = Field(default="v0", description="Compaction prompt template version")
    schema_version: int = 1
    created_at: datetime | None = None


class EngineeringCompaction(BaseCompaction):
    """Engineering-role compaction (v1)."""

    kind: Literal["engineering"] = "engineering"  # type: ignore[assignment]

    files_touched: list[str] = Field(default_factory=list)
    prs_opened: list[str] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    dead_end_branches: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)


# Discriminated union: pick the subclass by the ``kind`` literal.
Compaction = Annotated[
    EngineeringCompaction | BaseCompaction,
    Field(discriminator="kind"),
]

CompactionAdapter: TypeAdapter[BaseCompaction] = TypeAdapter(Compaction)


__all__ = [
    "BaseCompaction",
    "EngineeringCompaction",
    "Compaction",
    "CompactionAdapter",
]
