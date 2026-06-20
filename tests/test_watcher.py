"""Auto-capture daemon (`manthana watch`) — change detection + dispatch.

Hermetic: a real ClaudeCodeCollector pointed at a tmp projects dir (so
discover()/os.stat work on real files), but `ingest`/`compact_fn`/`sleep` are
injected, so no real transcripts, store writes, or model calls happen. Filesystem
changes are driven from the injected `sleep` (called between cycles).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from manthana.agent.capture import IngestResult
from manthana.agent.store import Store
from manthana.agent.watcher import watch
from manthana.collectors import ClaudeCodeCollector
from manthana.schemas import EngineeringCompaction, Outcome, Role, Session, Surface, Turn


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


def test_scan_survives_discover_error(tmp_path: Path) -> None:
    # A glob failure in discover() must not crash the loop (logged + skipped).
    class _BoomCollector:
        def discover(self) -> list[str]:
            raise PermissionError("projects dir not readable")

    calls, ingest = _recorder()
    watch(
        Store.open_memory(),
        collector=_BoomCollector(),  # type: ignore[arg-type]
        ingest=ingest,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=1,
    )
    assert calls == []  # nothing ingested, but no exception escaped


# ── atomic re-ingest (Store.replace_session_family) ─────────────────────────
def _sess(sid: str) -> Session:
    return Session(
        id=sid,
        actor="e@x.com",
        surface=Surface.claude_code,
        project="p",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        turn_count=1,
    )


def _turn(sid: str, i: int) -> Turn:
    return Turn(
        id=f"{sid}-t{i}", session_id=sid, actor="e@x.com", seq=i, role=Role.user, content="hi"
    )


def test_replace_session_family_replaces_and_clears() -> None:
    store = Store.open_memory()
    store.replace_session_family("s1", [(_sess("s1"), [_turn("s1", 0)])])
    assert store.get_session("s1") is not None
    assert len(store.get_turns("s1")) == 1
    # re-ingest with a different shape: old turns gone, new persisted (idempotent)
    store.replace_session_family("s1", [(_sess("s1"), [_turn("s1", 0), _turn("s1", 1)])])
    assert len(store.get_turns("s1")) == 2
    # emptied transcript → family fully removed
    store.replace_session_family("s1", [])
    assert store.get_session("s1") is None
    assert store.get_turns("s1") == []


def test_reingest_preserves_compaction(tmp_path: Path) -> None:
    # Re-ingesting a transcript must NOT destroy an existing (possibly
    # released/synced) compaction — the dogfood daemon re-reads constantly.
    store = Store.open_memory()
    store.replace_session_family("s1", [(_sess("s1"), [_turn("s1", 0)])])
    store.upsert_compaction(
        EngineeringCompaction(
            id="comp-s1",
            session_id="s1",
            actor="e@x.com",
            surface=Surface.claude_code,
            project="p",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, tzinfo=UTC),
            duration_seconds=1.0,
            task_intent="x",
            approach="a",
            outcome=Outcome.success,
            est_cost_usd=0.5,
            tier_used="opus",
            released=True,
        )
    )
    store.replace_session_family("s1", [(_sess("s1"), [_turn("s1", 0), _turn("s1", 1)])])
    surviving = store.get_compaction("comp-s1")
    assert surviving is not None and surviving.released is True  # compaction preserved
    # but an explicit family delete still removes everything
    store.delete_session_family("s1")
    assert store.get_compaction("comp-s1") is None


def test_auto_sync_runs_each_cycle(tmp_path: Path) -> None:
    # Releases happen out-of-band (dashboard), so auto-sync runs every cycle,
    # not only when files changed.
    proj = tmp_path / "projects"
    _touch(proj / "p1" / "s1.jsonl")
    _calls, ingest = _recorder()
    synced: list[int] = []

    def fake_sync(_store: object) -> int:
        synced.append(1)
        return 2

    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sync_fn=fake_sync,  # type: ignore[arg-type]
        sync_min_interval=0.0,  # no throttle: sync every cycle
        sleep=_noop_sleep,
        iterations=2,
    )
    assert synced == [1, 1]  # called on both cycles (cycle 2 had no file changes)


def test_auto_sync_is_rate_limited(tmp_path: Path) -> None:
    # With a min interval and a clock that doesn't advance, sync runs once (first
    # cycle) and is throttled thereafter — no hammering the server every poll.
    proj = tmp_path / "projects"
    _touch(proj / "p1" / "s1.jsonl")
    _calls, ingest = _recorder()
    synced: list[int] = []

    def fake_sync(_store: object) -> int:
        synced.append(1)
        return 0

    watch(
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sync_fn=fake_sync,  # type: ignore[arg-type]
        sync_min_interval=60.0,
        clock=lambda: 100.0,  # frozen clock → never past the interval
        sleep=_noop_sleep,
        iterations=4,
    )
    assert synced == [1]  # only the first cycle synced


def test_auto_sync_error_does_not_kill_loop(tmp_path: Path) -> None:
    proj = tmp_path / "projects"
    _touch(proj / "p1" / "s1.jsonl")
    calls, ingest = _recorder()

    def boom_sync(_store: object) -> int:
        raise RuntimeError("network down")

    watch(  # must not raise
        Store.open_memory(),
        collector=_collector(proj),
        ingest=ingest,  # type: ignore[arg-type]
        sync_fn=boom_sync,  # type: ignore[arg-type]
        sleep=_noop_sleep,
        iterations=1,
    )
    assert calls == [str(proj / "p1" / "s1.jsonl")]  # capture still happened


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
