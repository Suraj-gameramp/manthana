"""Normalized ``Turn`` — one atomic unit of an AI session, surface-agnostic.

A single raw transcript line (e.g. one Claude Code ``assistant`` message) may
flatten into several Turns: one per ``text`` block and one per ``tool_use`` /
``tool_result`` block, ordered by ``seq``. This keeps the stored row flat
(per the decisions doc) while still representing the real multi-block structure
of transcripts found in ``~/.claude/projects/<slug>/<sessionId>.jsonl``.

Field mapping from the Claude Code JSONL format (verified against real data):

    session_id           <- .sessionId
    timestamp            <- .timestamp (ISO-8601; sparse on meta lines)
    role                 <- .message.role  (tool result -> Role.tool)
    content              <- .message.content (string) or text blocks
    tool_name/tool_input <- .message.content[] {type: tool_use} .name/.input
    tool_output/error    <- .message.content[] {type: tool_result} .content/.is_error
    tool_use_id          <- tool_use .id  /  tool_result .tool_use_id
    model                <- .message.model
    tokens_*             <- .message.usage.{input,output,cache_creation_input,
                            cache_read_input}_tokens
    source_event_id      <- .uuid          (documented Manthana extension)
    source_parent_id     <- .parentUuid    (documented Manthana extension)

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import Role


class Turn(BaseModel):
    """A single normalized turn within a session."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable unique id for this turn")
    session_id: str = Field(..., description="Owning session id")
    actor: str = Field(..., description="Engineer identity (e.g. org email)")
    seq: int = Field(..., description="Monotonic order of this turn within the session")
    timestamp: datetime | None = Field(default=None, description="Event time, if present")
    role: Role

    content: str | None = Field(default=None, description="Text content of the turn, if any")

    tool_name: str | None = Field(default=None, description="Tool name for a call or result")
    tool_input: dict[str, Any] | None = Field(default=None, description="Tool call arguments")
    tool_output: str | None = Field(default=None, description="Tool result content")
    tool_use_id: str | None = Field(default=None, description="Pairs a tool call with its result")

    model: str | None = Field(default=None, description="Model id (assistant turns)")
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None

    error: str | None = Field(default=None, description="Error string if the turn errored")

    # Provenance (documented Manthana extension): map back to the raw transcript
    # line so compactions can cite specific turns and the collector can pair
    # tool calls with results across lines.
    source_event_id: str | None = Field(default=None, description="Raw transcript uuid")
    source_parent_id: str | None = Field(default=None, description="Raw transcript parentUuid")


__all__ = ["Turn"]
