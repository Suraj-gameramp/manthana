"""``FrictionPoint`` — a single point of friction recorded on a compaction.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import FrictionCategory


class FrictionPoint(BaseModel):
    """One friction event, evidenced by specific turns."""

    model_config = ConfigDict(extra="forbid")

    category: FrictionCategory
    description: str
    turn_refs: list[str] = Field(
        default_factory=list, description="Turn ids that evidence this friction"
    )


__all__ = ["FrictionPoint"]
