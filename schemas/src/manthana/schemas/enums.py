"""Enumerations shared across all Manthana schemas.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from enum import StrEnum


class Surface(StrEnum):
    """The tool surface a session was captured from."""

    claude_code = "claude_code"
    codex = "codex"
    cursor = "cursor"  # reserved for v1.5


class Role(StrEnum):
    """Role of a normalized turn. ``tool`` denotes a tool *result*; a tool
    *call* is an ``assistant`` turn with ``tool_name`` set."""

    user = "user"
    assistant = "assistant"
    tool = "tool"


class Mode(StrEnum):
    """Work/Personal classification. Personal-mode data never leaves the laptop."""

    work = "work"
    personal = "personal"


class Outcome(StrEnum):
    """Terminal outcome of a session/compaction."""

    success = "success"
    partial = "partial"
    abandoned = "abandoned"


class FrictionCategory(StrEnum):
    """Categories of friction surfaced by the compactor / failure miner."""

    loop = "loop"
    tool_error = "tool_error"
    abandon = "abandon"
    retry = "retry"
    deadend = "deadend"


class SessionEndReason(StrEnum):
    """Why a session boundary was drawn (see decisions doc: capture rules)."""

    gap = "gap"  # >30 min since last turn
    stop_hook = "stop_hook"  # clean exit / Stop hook fired
    cap = "cap"  # >6 h continuous activity cap
    open = "open"  # not yet ended


class CompactionKind(StrEnum):
    """Discriminator for the polymorphic compaction hierarchy."""

    base = "base"
    engineering = "engineering"


class ActionShape(StrEnum):
    """What shape an action takes (actions catalog)."""

    read = "read"
    write = "write"
    warn = "warn"
    notify = "notify"


class ActionActor(StrEnum):
    """Who performs an action."""

    engineer = "engineer"  # local agent, engineer's own data
    org = "org"  # server, organization scope


class ConsentClass(StrEnum):
    """Consent class an action requires (actions catalog)."""

    silent = "silent"
    opt_out = "opt_out"
    opt_in = "opt_in"
    per_action = "per_action"


class ConsentState(StrEnum):
    """Per-subject consent state in the consent registry."""

    opt_in = "opt_in"
    opt_out = "opt_out"
    default = "default"


class ActionOutcome(StrEnum):
    """Outcome recorded in the action audit log when an action is evaluated."""

    fired = "fired"
    suppressed = "suppressed"  # cooldown / consent / k-anonymity / threshold
    failed = "failed"


class QueueStatus(StrEnum):
    """Status of a server-side pending action awaiting human approval."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


__all__ = [
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
