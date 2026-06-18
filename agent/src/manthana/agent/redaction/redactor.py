"""Redaction pipeline.

Regex-based scrubbing of secrets and PII, plus governance detectors (approval
commands, sensitive paths) carried over from ECC. Redaction produces *copies*:
the employee's local store keeps full fidelity; redaction is applied on the path
to release / in the review-before-sync preview (so the employee sees exactly what
will leave the laptop). An optional LLM scrubber hook is supported but disabled
by default; the concrete provider arrives with the compactor (Phase 4).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, overload

from manthana.schemas import BaseCompaction, Turn

from .patterns import APPROVAL_COMMANDS, PII_PATTERNS, SECRET_PATTERNS, SENSITIVE_PATHS

PLACEHOLDER = "[REDACTED:{name}]"

# Compaction fields that are structural / grouping / ids — never redacted (else
# server grouping, k-anon buckets, and citations break). Everything else that is
# str or list[str] is redacted by default (future subclass fields included).
_COMPACTION_KEEP = frozenset(
    {
        "id",
        "session_id",
        "actor",
        "surface",
        "project",
        "kind",
        "tier_used",
        "outcome",
        "prompt_version",
        "action_triggers",
    }
)


@dataclass
class RedactionConfig:
    """Which redaction categories are active, plus any custom patterns."""

    redact_secrets: bool = True
    redact_pii: bool = True
    extra_patterns: list[tuple[str, re.Pattern[str]]] = field(default_factory=list)
    # Optional LLM-based scrubber: text -> scrubbed text. Default off (Phase 4).
    llm_scrub: Callable[[str], str] | None = None


class Redactor:
    """Scrubs secrets/PII from text and turns; flags governance-relevant items."""

    def __init__(self, config: RedactionConfig | None = None) -> None:
        self.config = config or RedactionConfig()

    def _active_patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        patterns: list[tuple[str, re.Pattern[str]]] = []
        if self.config.redact_secrets:
            patterns += SECRET_PATTERNS
        if self.config.redact_pii:
            patterns += PII_PATTERNS
        patterns += self.config.extra_patterns
        return patterns

    def detect(self, text: str | None) -> list[str]:
        """Return the names of every pattern that matches (for governance/audit)."""
        if not text:
            return []
        return [name for name, pattern in self._active_patterns() if pattern.search(text)]

    @overload
    def redact_text(self, text: str) -> str: ...
    @overload
    def redact_text(self, text: None) -> None: ...
    @overload
    def redact_text(self, text: str | None) -> str | None: ...
    def redact_text(self, text: str | None) -> str | None:
        if not text:
            return text
        out = text
        for name, pattern in self._active_patterns():
            out = pattern.sub(PLACEHOLDER.format(name=name), out)
        if self.config.llm_scrub is not None:
            out = self.config.llm_scrub(out)
        return out

    def redact_value(self, value: Any) -> Any:
        """Recursively redact string values AND string keys inside dicts/lists."""
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {
                (self.redact_text(k) if isinstance(k, str) else k): self.redact_value(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.redact_value(v) for v in value]
        return value

    def redact_turn(self, turn: Turn) -> Turn:
        """Return a redacted COPY of a turn (original is left untouched).

        Redacts every free-text field — including ``error`` (stack traces can echo
        secrets/PII) and dict keys/values in ``tool_input``."""
        return turn.model_copy(
            update={
                "content": self.redact_text(turn.content),
                "tool_output": self.redact_text(turn.tool_output),
                "error": self.redact_text(turn.error),
                "tool_input": (
                    self.redact_value(turn.tool_input) if turn.tool_input else turn.tool_input
                ),
            }
        )

    def redact_turns(self, turns: list[Turn]) -> list[Turn]:
        return [self.redact_turn(t) for t in turns]

    def redact_compaction(self, compaction: BaseCompaction) -> BaseCompaction:
        """Return a redacted COPY of a compaction, applied on the path to release.

        Default-redacts EVERY str / list[str] field (so subclass fields like
        EngineeringCompaction.files_touched are scrubbed too) except structural,
        grouping, and id fields in ``_COMPACTION_KEEP``; friction descriptions are
        redacted explicitly. Subclass + extra fields are preserved by model_copy.
        """
        update: dict[str, Any] = {}
        for name in type(compaction).model_fields:
            if name in _COMPACTION_KEEP or name == "friction_points":
                continue
            value = getattr(compaction, name)
            if isinstance(value, str):
                update[name] = self.redact_text(value)
            elif isinstance(value, list) and value and all(isinstance(x, str) for x in value):
                update[name] = [self.redact_text(x) for x in value]
        update["friction_points"] = [
            fp.model_copy(update={"description": self.redact_text(fp.description)})
            for fp in compaction.friction_points
        ]
        return compaction.model_copy(update=update)

    # ── governance detectors (from ECC; not redaction, but available) ──────
    def detect_approval_required(self, command: str | None) -> list[str]:
        if not command:
            return []
        return [p.pattern for p in APPROVAL_COMMANDS if p.search(command)]

    def detect_sensitive_path(self, path: str | None) -> bool:
        if not path:
            return False
        return any(p.search(path) for p in SENSITIVE_PATHS)


__all__ = ["Redactor", "RedactionConfig", "PLACEHOLDER"]
