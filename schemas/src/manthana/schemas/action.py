"""Action seam schemas — present in v1 even though most handlers ship v1.5+.

These model the architectural seams the decisions doc requires so future actions
ship as new handlers against existing infrastructure rather than as schema
migrations:

* ``Action``          — the catalog/registry entry defining an action type.
* ``ActionAuditEntry``— the audit log: every fired/suppressed action.
* ``ActionQueueItem`` — server-side pending action awaiting human approval.

(``ConsentEntry`` lives in ``consent.py``.)

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import ActionActor, ActionOutcome, ActionShape, ConsentClass, QueueStatus


class Action(BaseModel):
    """Definition of a Manthana action type (the registry/catalog entry)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable action id, e.g. 'auto_tag_sessions'")
    name: str
    shape: ActionShape
    actor: ActionActor
    consent_class: ConsentClass
    version: str = "0.1.0"
    enabled: bool = True
    confidence_threshold: float | None = Field(
        default=None, description="Minimum measured signal to fire (e.g. cosine similarity)"
    )
    cooldown_seconds: int | None = Field(
        default=None, description="Min seconds between fires for the same trigger"
    )
    description: str = ""


class ActionAuditEntry(BaseModel):
    """One evaluated action — the audit log seam.

    Logged for every fire AND every suppression (cooldown/consent/k-anonymity/
    threshold) so actions are correctable rather than authoritative.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    action_id: str
    actor: str | None = Field(default=None, description="Subject the action acted for/on")
    fired_at: datetime
    trigger_condition: str = Field(..., description="Human-readable trigger that matched")
    confidence: float | None = None
    outcome: ActionOutcome
    useful: bool | None = Field(
        default=None, description="Feedback (useful/not-useful); UI deferred to v1.5"
    )
    details: dict[str, Any] = Field(default_factory=dict)


class ActionQueueItem(BaseModel):
    """Server-side pending action awaiting human approval — the queue seam.

    Empty in v1; populated by org-mutating actions (auto-drafted skills, opened
    issues, routing changes) in v1.5+.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    action_id: str
    team_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: QueueStatus = QueueStatus.pending
    created_at: datetime
    approved_by: str | None = None
    resolved_at: datetime | None = None


__all__ = ["Action", "ActionAuditEntry", "ActionQueueItem"]
