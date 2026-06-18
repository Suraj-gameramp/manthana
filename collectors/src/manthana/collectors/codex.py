"""Codex CLI collector — registered stub (v1).

The spec references ``~/.codex/sessions/`` but current Codex stores SQLite and
no JSONL transcripts were found on the verified machine (see
``manthana-decisions.md`` correction, 2026-06-19). This collector exists so the
registry seam is exercised and the Codex surface is reserved; ``parse`` is
implemented once a real rollout format / sample data is available.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterator

from manthana.schemas import Surface, Turn


class CodexCollector:
    """Placeholder Codex collector (no local data yet)."""

    surface: Surface = Surface.codex

    def discover(self) -> list[str]:
        return []

    def parse(self, source: str) -> Iterator[Turn]:
        raise NotImplementedError(
            "Codex collector not implemented: no verified local transcript format. "
            "See spec/manthana-decisions.md (2026-06-19 correction)."
        )
        yield  # pragma: no cover - marks this a generator for the protocol


__all__ = ["CodexCollector"]
