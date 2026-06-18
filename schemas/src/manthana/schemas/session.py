"""``Session`` — a contiguous block of turns on one surface.

Session boundaries are inferred by the collector (decisions doc, capture rules):
a new session is triggered by a >30 min gap, a clean Stop-hook exit, or a >6 h
continuous-activity cap. ``--resume`` within 30 min extends the current session;
outside the window it creates a new session linked via ``resumed_from``.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import Mode, SessionEndReason, Surface


class Session(BaseModel):
    """A normalized session across any captured surface."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable session id (surface session UUID when available)")
    actor: str = Field(..., description="Engineer identity (e.g. org email)")
    surface: Surface
    project: str = Field(..., description="Inferred project name (git toplevel or cwd basename)")
    repo_root: str | None = Field(default=None, description="git rev-parse --show-toplevel, if any")

    started_at: datetime
    ended_at: datetime | None = None
    ended_reason: SessionEndReason = SessionEndReason.open

    turn_count: int = 0
    mode: Mode = Field(default=Mode.work, description="Work/Personal; personal never syncs")

    resumed_from: str | None = Field(
        default=None, description="Prior session id when a --resume crossed the 30-min window"
    )
    source_path: str | None = Field(
        default=None, description="Transcript file path this session was parsed from"
    )


__all__ = ["Session"]
