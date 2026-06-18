"""Collector abstraction (architectural seam).

Each capture surface implements the ``Collector`` protocol and registers itself.
The pattern is re-expressed from the adapter-registry design in
affaan-m/ECC ``scripts/lib/session-adapters/`` (registry.js + canonical-session.js
+ claude-history.js; MIT, 2026 Affaan Mustafa). ECC's canonical session is
orchestration-centric (worker states); Manthana's canonical model is the flat
``Turn`` / ``Session`` pair, so the adapters turn raw transcripts into ``Turn``s
rather than ECC's canonical session.

v1 registers the Claude Code collector (Phase 2) and a Codex stub; v1.5 adds
Cursor without touching this seam.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, runtime_checkable

from manthana.schemas import Surface, Turn


@runtime_checkable
class Collector(Protocol):
    """A surface adapter that discovers transcripts and yields normalized turns."""

    surface: Surface

    def discover(self) -> Iterable[str]:
        """Yield transcript source identifiers (e.g. file paths) for this surface."""
        ...

    def parse(self, source: str) -> Iterator[Turn]:
        """Parse one transcript source into normalized ``Turn``s, in order."""
        ...


_REGISTRY: dict[str, Collector] = {}


def register(collector: Collector) -> Collector:
    """Register a collector under its surface id. Returns the collector."""
    _REGISTRY[collector.surface.value] = collector
    return collector


def get(surface: str) -> Collector | None:
    """Look up a registered collector by surface id."""
    return _REGISTRY.get(surface)


def registered() -> list[str]:
    """List registered surface ids."""
    return sorted(_REGISTRY)


__all__ = ["Collector", "register", "get", "registered"]
