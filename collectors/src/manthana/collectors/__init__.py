"""Manthana collectors — per-surface adapters that normalize raw transcripts
into ``Turn``s. See ``manthana.collectors.base`` for the registry seam.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from .base import Collector, get, register, registered
from .claude_code import ClaudeCodeCollector
from .codex import CodexCollector
from .identity import resolve_actor
from .project import infer_project
from .sessionize import sessionize


def register_builtin(actor: str | None = None) -> None:
    """Register the v1 built-in collectors into the shared registry."""
    register(ClaudeCodeCollector(actor=actor))
    register(CodexCollector())


__all__ = [
    "Collector",
    "register",
    "get",
    "registered",
    "register_builtin",
    "ClaudeCodeCollector",
    "CodexCollector",
    "sessionize",
    "infer_project",
    "resolve_actor",
]
