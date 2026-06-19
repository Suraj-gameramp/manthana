"""Protocols the skill miner depends on, kept package-local so the shared miner
pulls in neither the local agent nor the server.

``LLMProvider`` is structurally satisfied by both ``manthana.agent.llm`` and
``manthana.server.llm`` providers; ``SupportsRedaction`` by the agent's
``Redactor`` (the server passes ``None`` — its compactions are already redacted
on sync).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from manthana.schemas import BaseCompaction


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str: ...


@runtime_checkable
class SupportsRedaction(Protocol):
    def redact_compaction(self, compaction: BaseCompaction) -> BaseCompaction: ...


__all__ = ["LLMProvider", "SupportsRedaction"]
