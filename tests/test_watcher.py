"""Auto-capture daemon (`manthana watch`) — change detection + dispatch.

Hermetic: a real ClaudeCodeCollector pointed at a tmp projects dir (so
discover()/os.stat work on real files), but `ingest`/`compact_fn`/`sleep` are
injected, so no real transcripts, store writes, or model calls happen. Filesystem
changes are driven from the injected `sleep` (called between cycles).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
from pathlib import Path

from manthana.agent.capture import IngestResult
from manthana.agent.store import Store
from manthana.agent.watcher import watch
from manthana.collectors import ClaudeCodeCollector


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _collector(projects: Path) -> ClaudeCodeCollector:
    return ClaudeCodeCollector(actor="e@x.com", projects_dir=projects)


def _recorder() -> tuple[list[str], object]:
    calls: list[str] = []

    def fake_ingest(_store: object, source: str, *, collector: object = None) -> IngestResult:
        calls.append(source)
        return IngestResult(source=source, sessions=[])

    return calls, fake_ingest


def _noop_sleep(_seconds: float) -> None:
    return None


def test_first_cycle_catches_up_existing(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    f1 = proj / "p1" / "s1.jsonl"
    _touch(f1)
    calls, ingest = _recorder()
    seen = watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=1,
    )
    assert calls == [str(f1)]
    assert str(f1) in seen


def test_unchanged_file_not_reingested(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    _touch(proj / "p1" / "s1.jsonl")
    calls, ingest = _recorder()
    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=3,  # three cycles, but the file is stable
    )
    assert len(calls) == 1  # ingested once, then skipped


def test_new_file_picked_up_next_cycle(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    f1 = proj / "p1" / "s1.jsonl"
    f2 = proj / "p1" / "s2.jsonl"
    _touch(f1)
    calls, ingest = _recorder()

    def add_f2_between_cycles(_seconds: float) -> None:
        if not f2.exists():
            _touch(f2)

    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sleep=add_f2_between_cycles,
        iterations=2,
    )
    assert calls == [str(f1), str(f2)]


def test_modified_file_reingested(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    f1 = proj / "p1" / "s1.jsonl"
    _touch(f1)
    calls, ingest = _recorder()

    def bump_mtime(_seconds: float) -> None:
        future = f1.stat().st_mtime + 100
        os.utime(f1, (future, future))

    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sleep=bump_mtime,
        iterations=2,
    )
    assert calls == [str(f1), str(f1)]  # changed mtime → re-ingested


def test_ingest_error_isolated_and_retried(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    f1 = proj / "p1" / "s1.jsonl"  # sorts before s2 → fails first
    f2 = proj / "p1" / "s2.jsonl"
    _touch(f1)
    _touch(f2)
    ok: list[str] = []

    def flaky_ingest(_store: object, source: str, *, collector: object = None) -> IngestResult:
        if source == str(f1):
            raise RuntimeError("bad transcript")
        ok.append(source)
        return IngestResult(source=source, sessions=[])

    seen = watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=flaky_ingest,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=1,
    )
    assert ok == [str(f2)]  # f2 ingested despite f1 raising
    assert str(f1) not in seen  # failed file not remembered → retried next cycle
    assert str(f2) in seen


def test_compact_flag_invokes_compact_fn(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    _touch(proj / "p1" / "s1.jsonl")
    _calls, ingest = _recorder()
    compacted: list[bool] = []

    def fake_compact(_store: object, *, provider: object = None) -> list[object]:
        compacted.append(True)
        return []

    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        compact=True,
        compact_fn=fake_compact,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=1,
    )
    assert compacted == [True]


def test_no_compaction_by_default(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    _touch(proj / "p1" / "s1.jsonl")
    _calls, ingest = _recorder()
    compacted: list[bool] = []

    def fake_compact(_store: object, *, provider: object = None) -> list[object]:
        compacted.append(True)
        return []

    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        compact_fn=fake_compact,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=1,
    )
    assert compacted == []  # capture-only default never compacts
