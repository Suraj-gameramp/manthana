"""Schema round-trip + JSON Schema mirror guard.

1. The polymorphic compaction union resolves the right subclass by ``kind``.
2. The committed ``schemas/json/*.schema.json`` match the live Pydantic models,
   so the cross-language mirror never silently drifts. Regenerate with
   ``uv run manthana-schemas-export``.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from manthana.schemas import (
    BaseCompaction,
    CompactionAdapter,
    EngineeringCompaction,
    Outcome,
    Surface,
)
from manthana.schemas import export as export_mod

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _engineering() -> EngineeringCompaction:
    return EngineeringCompaction(
        id="c1",
        session_id="s1",
        actor="e",
        surface=Surface.claude_code,
        project="p",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=2.0,
        task_intent="t",
        approach="a",
        outcome=Outcome.success,
        files_touched=["a.py"],
        languages=["python"],
    )


def test_engineering_compaction_roundtrips_via_union() -> None:
    data = _engineering().model_dump(mode="json")
    assert data["kind"] == "engineering"
    parsed = CompactionAdapter.validate_python(data)
    assert isinstance(parsed, EngineeringCompaction)
    assert parsed.files_touched == ["a.py"]


def test_base_compaction_discriminates_to_base() -> None:
    bc = BaseCompaction(
        id="c2",
        session_id="s",
        actor="e",
        surface=Surface.codex,
        project="p",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent="t",
        approach="a",
        outcome=Outcome.partial,
    )
    parsed = CompactionAdapter.validate_python(bc.model_dump(mode="json"))
    assert type(parsed) is BaseCompaction


def test_json_schema_mirror_in_sync(tmp_path: Path) -> None:
    written = export_mod.export(tmp_path)
    committed_dir = export_mod.schema_dir()
    for path in written:
        committed = committed_dir / path.name
        assert committed.exists(), (
            f"missing committed schema {committed.name}; run `uv run manthana-schemas-export`"
        )
        assert committed.read_text() == path.read_text(), (
            f"{path.name} drifted from the model; run `uv run manthana-schemas-export`"
        )
