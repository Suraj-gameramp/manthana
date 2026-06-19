"""Auto-capture daemon: poll the Claude Code transcript dir and ingest changes.

``watch`` is a stdlib polling loop (deliberately no ``watchdog`` dependency). It
tracks each transcript's mtime and re-ingests only new/changed files via the
incremental, idempotent ``ingest_file``. Capture-only by default; ``compact=True``
also runs ``compact_pending`` after a change (which spends model tokens).

Everything external (the collector, the ingest/compact callables, ``sleep``, the
log sink, and the cycle count) is injectable so the loop is hermetically testable
without a real ``~/.claude`` or a real model.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from manthana.collectors import ClaudeCodeCollector

from .capture import IngestResult, ingest_file
from .compact import compact_pending
from .llm import LLMProvider
from .store import Store

_log = logging.getLogger(__name__)


def _scan(collector: ClaudeCodeCollector) -> dict[str, float]:
    """Map each discovered transcript to its mtime (raced/removed files skipped)."""
    out: dict[str, float] = {}
    for src in collector.discover():
        try:
            out[src] = os.stat(src).st_mtime
        except OSError:
            continue  # file vanished between discover() and stat() — pick it up later
    return out


def watch(
    store: Store,
    *,
    collector: ClaudeCodeCollector | None = None,
    interval: float = 5.0,
    compact: bool = False,
    provider: LLMProvider | None = None,
    iterations: int | None = None,
    ingest: Callable[..., IngestResult] = ingest_file,
    compact_fn: Callable[..., list[Any]] = compact_pending,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] | None = None,
) -> dict[str, float]:
    """Poll for new/changed transcripts and ingest them until stopped.

    The first cycle has an empty ``seen`` map, so it catches up every existing
    transcript; later cycles ingest only files whose mtime changed. A file that
    fails to ingest is logged and *not* remembered, so it is retried next cycle.
    Runs forever unless ``iterations`` bounds the cycle count (tests). Returns the
    final ``{path: mtime}`` map.
    """
    collector = collector or ClaudeCodeCollector()
    emit = log or _log.info
    seen: dict[str, float] = {}
    cycle = 0
    while iterations is None or cycle < iterations:
        current = _scan(collector)
        changed = [path for path, mtime in current.items() if seen.get(path) != mtime]
        if changed:
            sessions = turns = ok = 0
            for src in changed:
                try:
                    result = ingest(store, src, collector=collector)
                except Exception:  # noqa: BLE001 - one bad transcript must not kill the loop
                    _log.exception("watch: failed to ingest %s", src)
                    continue
                sessions += result.session_count
                turns += result.turn_count
                ok += 1
                seen[src] = current[src]  # remember only cleanly-ingested files
            emit(f"ingested {ok} files -> {sessions} sessions, {turns} turns")
            if compact:
                try:
                    comps = compact_fn(store, provider=provider)
                    emit(f"compacted {len(comps)} pending sessions")
                except Exception:  # noqa: BLE001 - compaction failure must not kill the loop
                    _log.exception("watch: compaction failed")
        # Forget files that disappeared so a recreated path re-ingests.
        seen = {path: mtime for path, mtime in seen.items() if path in current}
        cycle += 1
        if iterations is not None and cycle >= iterations:
            break
        sleep(interval)
    return seen


__all__ = ["watch"]
