"""Capture pipeline: transcripts -> normalized Sessions/Turns -> local store.

Ties the Claude Code collector to the SQLite store. New sessions default to Work
mode (decisions doc); the Work/Personal toggle and redaction land in Phase 3.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dataclasses import dataclass

from manthana.collectors import ClaudeCodeCollector, infer_project, resolve_actor, sessionize
from manthana.schemas import Mode, Session, Surface

from .store import Store


@dataclass
class IngestResult:
    source: str
    sessions: list[Session]

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def turn_count(self) -> int:
        return sum(s.turn_count for s in self.sessions)


def ingest_file(
    store: Store,
    source: str,
    *,
    actor: str | None = None,
    mode: Mode = Mode.work,
    collector: ClaudeCodeCollector | None = None,
) -> IngestResult:
    """Parse one Claude Code transcript and persist its Session(s) and Turns."""
    actor = actor or resolve_actor()
    collector = collector or ClaudeCodeCollector(actor=actor)
    turns, meta = collector.read(source)
    project, repo_root = infer_project(meta.cwd)

    sessions = sessionize(
        turns,
        surface=Surface.claude_code,
        actor=actor,
        project=project,
        repo_root=repo_root,
        base_session_id=meta.session_id,
        source_path=source,
        fallback_time=meta.mtime,
        mode=mode,
    )

    persisted: list[Session] = []
    for session, seg_turns in sessions:
        store.upsert_session(session)
        store.add_turns(seg_turns)
        persisted.append(session)
    return IngestResult(source=source, sessions=persisted)


def ingest_all(
    store: Store,
    *,
    actor: str | None = None,
    mode: Mode = Mode.work,
) -> list[IngestResult]:
    """Discover and ingest every Claude Code transcript on this machine."""
    actor = actor or resolve_actor()
    collector = ClaudeCodeCollector(actor=actor)
    return [
        ingest_file(store, source, actor=actor, mode=mode, collector=collector)
        for source in collector.discover()
    ]


__all__ = ["ingest_file", "ingest_all", "IngestResult"]
