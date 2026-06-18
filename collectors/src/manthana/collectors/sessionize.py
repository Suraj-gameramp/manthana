"""Surface-agnostic session boundary inference.

Decisions doc (capture, session boundary rule): a session is a contiguous block
of turns. A new session is triggered by

  1. a >30 minute gap since the last turn, OR
  2. a clean Stop-hook exit (live daemon only; not observable in batch), OR
  3. a >6 hour continuous-activity cap since session start.

``--resume`` within the 30-min window extends the current session; outside it,
a new session is created and linked to the prior one via ``resumed_from``. A
single transcript file (one surface session id) may therefore split into several
Manthana sessions, chained by ``resumed_from``.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime, timedelta

from manthana.schemas import Mode, Session, SessionEndReason, Surface, Turn

GAP = timedelta(minutes=30)
CAP = timedelta(hours=6)


def _segment(turns: list[Turn]) -> list[tuple[list[Turn], SessionEndReason]]:
    """Split ordered turns into (segment, end_reason) pairs by the gap/cap rules.

    Timestamps are carried forward for turns that lack one (meta lines), per the
    field-map note. The end_reason marks why a segment closed; the final segment
    is ``open`` (a batch parse cannot observe a clean stop).
    """
    segments: list[tuple[list[Turn], SessionEndReason]] = []
    current: list[Turn] = []
    seg_start: datetime | None = None
    last_ts: datetime | None = None

    for turn in turns:
        ts = turn.timestamp or last_ts
        if current and ts is not None and seg_start is not None and last_ts is not None:
            if ts - last_ts > GAP:
                segments.append((current, SessionEndReason.gap))
                current, seg_start = [], None
            elif ts - seg_start > CAP:
                segments.append((current, SessionEndReason.cap))
                current, seg_start = [], None
        if not current:
            seg_start = ts
        current.append(turn)
        # Late-init: if the segment opened with timestamp-less turns, anchor
        # seg_start to the first real timestamp so the cap check works.
        if seg_start is None and ts is not None:
            seg_start = ts
        if ts is not None:
            last_ts = ts

    if current:
        segments.append((current, SessionEndReason.open))
    return segments


def sessionize(
    turns: list[Turn],
    *,
    surface: Surface,
    actor: str,
    project: str,
    repo_root: str | None,
    base_session_id: str,
    source_path: str | None,
    fallback_time: datetime,
    mode: Mode = Mode.work,
) -> list[tuple[Session, list[Turn]]]:
    """Group ordered turns into Sessions with their (re-sequenced) turns."""
    results: list[tuple[Session, list[Turn]]] = []
    prev_id: str | None = None

    for index, (segment, reason) in enumerate(_segment(turns)):
        session_id = base_session_id if index == 0 else f"{base_session_id}.{index + 1}"
        seg_turns = [
            turn.model_copy(update={"session_id": session_id, "seq": seq})
            for seq, turn in enumerate(segment)
        ]
        times = [t.timestamp for t in segment if t.timestamp is not None]
        started_at = times[0] if times else fallback_time
        ended_at = times[-1] if times else None

        session = Session(
            id=session_id,
            actor=actor,
            surface=surface,
            project=project,
            repo_root=repo_root,
            started_at=started_at,
            ended_at=ended_at,
            ended_reason=reason,
            turn_count=len(seg_turns),
            mode=mode,
            resumed_from=prev_id,
            source_path=source_path,
        )
        results.append((session, seg_turns))
        prev_id = session_id

    return results


__all__ = ["sessionize", "GAP", "CAP"]
