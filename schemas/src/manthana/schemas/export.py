"""Export Pydantic models to mirrored JSON Schema files.

The JSON Schema mirror lets non-Python collectors and CI validate the same
contracts (decisions doc: "JSON Schema mirrored from Pydantic models for
cross-language reuse and CI validation"). Regenerate after any model change:

    uv run manthana-schemas-export

A test (``tests/test_schema_roundtrip.py``) fails if the committed files under
``schemas/json/`` drift from the live models.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .action import Action, ActionAuditEntry, ActionQueueItem
from .compaction import BaseCompaction, EngineeringCompaction
from .consent import ConsentEntry
from .friction import FrictionPoint
from .session import Session
from .turn import Turn

MODELS: dict[str, type[BaseModel]] = {
    "turn": Turn,
    "session": Session,
    "friction_point": FrictionPoint,
    "base_compaction": BaseCompaction,
    "engineering_compaction": EngineeringCompaction,
    "action": Action,
    "action_audit_entry": ActionAuditEntry,
    "action_queue_item": ActionQueueItem,
    "consent_entry": ConsentEntry,
}


def schema_dir() -> Path:
    """Committed JSON Schema directory: ``schemas/json/``."""
    return Path(__file__).resolve().parents[3] / "json"


def render(model: type[BaseModel]) -> str:
    """Deterministic JSON Schema text for one model."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export(out_dir: Path | None = None) -> list[Path]:
    """Write every model's JSON Schema to ``out_dir`` (default ``schemas/json``)."""
    out = out_dir or schema_dir()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        path = out / f"{name}.schema.json"
        path.write_text(render(model))
        written.append(path)
    return written


def main() -> None:
    for path in export():
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
