"""High-level compaction orchestration: load a session, compact it, store it.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from manthana.schemas import EngineeringCompaction, Mode

from .compactor import Compactor
from .llm import LLMProvider, default_provider
from .store import Store


def compact_session(
    store: Store,
    session_id: str,
    *,
    provider: LLMProvider | None = None,
) -> EngineeringCompaction | None:
    """Compact one stored session and persist the result. None if not found."""
    session = store.get_session(session_id)
    if session is None:
        return None
    turns = store.get_turns(session_id)
    compaction = Compactor(provider or default_provider()).compact(session, turns)
    store.upsert_compaction(compaction)
    return compaction


def compact_pending(
    store: Store,
    *,
    provider: LLMProvider | None = None,
    limit: int | None = None,
) -> list[EngineeringCompaction]:
    """Compact Work-mode sessions that don't yet have a compaction.

    Personal-mode sessions are skipped (they never contribute to anything that
    could be released).
    """
    provider = provider or default_provider()
    existing = {c.session_id for c in store.list_compactions()}
    out: list[EngineeringCompaction] = []
    for session in store.list_sessions(limit=limit):
        if session.mode is Mode.personal or session.id in existing:
            continue
        compaction = Compactor(provider).compact(session, store.get_turns(session.id))
        store.upsert_compaction(compaction)
        out.append(compaction)
    return out


__all__ = ["compact_session", "compact_pending"]
