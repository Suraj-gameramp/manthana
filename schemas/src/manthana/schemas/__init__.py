"""Manthana shared schemas (Pydantic v2 + mirrored JSON Schema).

This package is the single source of truth for Manthana's data contracts. The
mirrored JSON Schema under ``schemas/json/`` is generated from these models via
``manthana-schemas-export`` and guarded by a CI test.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from .action import Action, ActionAuditEntry, ActionQueueItem
from .compaction import (
    BaseCompaction,
    Compaction,
    CompactionAdapter,
    EngineeringCompaction,
)
from .consent import ConsentEntry
from .enums import (
    ActionActor,
    ActionOutcome,
    ActionShape,
    CompactionKind,
    ConsentClass,
    ConsentState,
    FrictionCategory,
    Mode,
    Outcome,
    QueueStatus,
    Role,
    SessionEndReason,
    Surface,
)
from .friction import FrictionPoint
from .session import Session
from .turn import Turn

__all__ = [
    # entities
    "Turn",
    "Session",
    "FrictionPoint",
    "BaseCompaction",
    "EngineeringCompaction",
    "Compaction",
    "CompactionAdapter",
    "Action",
    "ActionAuditEntry",
    "ActionQueueItem",
    "ConsentEntry",
    # enums
    "Surface",
    "Role",
    "Mode",
    "Outcome",
    "FrictionCategory",
    "SessionEndReason",
    "CompactionKind",
    "ActionShape",
    "ActionActor",
    "ConsentClass",
    "ConsentState",
    "ActionOutcome",
    "QueueStatus",
]
