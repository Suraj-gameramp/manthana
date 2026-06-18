"""``ConsentEntry`` — the consent registry seam.

Per-engineer and per-admin opt-in/opt-out state per action category. v1 has the
registry; v1.5+ adds the UI to manage it. The override hierarchy (engineer
opt-out wins for own data; org opt-out wins for boundary-crossing actions;
personal-mode excluded from all actions) is enforced by the dispatcher, not the
schema.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import ConsentState


class ConsentEntry(BaseModel):
    """One consent decision by a subject for an action category."""

    model_config = ConfigDict(extra="forbid")

    id: str
    subject: str = Field(..., description="Actor id (engineer) or 'org' / 'admin:<id>'")
    action_category: str = Field(..., description="Action id or category")
    state: ConsentState = ConsentState.default
    scope: str = Field(default="engineer", description="engineer | org")
    set_at: datetime


__all__ = ["ConsentEntry"]
