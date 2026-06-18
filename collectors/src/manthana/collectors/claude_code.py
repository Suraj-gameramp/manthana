"""Claude Code collector.

Reads ``~/.claude/projects/<slug>/<sessionId>.jsonl`` and flattens each line into
normalized ``Turn``s. The JSONL parsing is written fresh against the format
verified from real transcripts (see ``manthana.schemas.turn`` field map); only the
adapter/registry *shape* is reused from affaan-m/ECC
``scripts/lib/session-adapters/`` (MIT, 2026 Affaan Mustafa). Robust line handling
(skip unparseable lines, string-or-array content, nested blocks) follows the
edge cases in ECC ``scripts/hooks/session-end.js`` ``extractSessionSummary``.

Flattening (one transcript line -> 0..N Turns, ordered by ``seq``):
  * user text          -> Turn(role=user, content)
  * user tool_result   -> Turn(role=tool, tool_output, error, tool_use_id)
  * assistant text     -> Turn(role=assistant, content, model)
  * assistant tool_use -> Turn(role=assistant, tool_name, tool_input, tool_use_id, model)
  * assistant thinking -> skipped
Per-line token usage is attached to exactly one Turn from that line (never
double-counted); an assistant line that emits no text/tool_use but carries usage
still yields one carrier Turn so cost is preserved.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from manthana.schemas import Role, Surface, Turn

from .identity import resolve_actor

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class FileMeta:
    """Metadata about a parsed transcript file."""

    session_id: str
    cwd: str | None
    git_branch: str | None
    mtime: datetime


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _stringify(content: object) -> str | None:
    """Flatten a tool_result content (str, list of blocks, or other) to text."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def _make_turn(
    *,
    actor: str,
    base_id: str,
    role: Role,
    ts: datetime | None,
    uuid: object,
    parent: object,
    **fields: Any,
) -> Turn:
    return Turn(
        id="",  # assigned after full ordering
        session_id=base_id,
        actor=actor,
        seq=0,
        timestamp=ts,
        role=role,
        source_event_id=uuid if isinstance(uuid, str) else None,
        source_parent_id=parent if isinstance(parent, str) else None,
        **fields,
    )


class ClaudeCodeCollector:
    """Collector for the Claude Code surface."""

    surface: Surface = Surface.claude_code

    def __init__(self, actor: str | None = None, projects_dir: Path | None = None) -> None:
        self.actor = actor or resolve_actor()
        self.projects_dir = projects_dir or DEFAULT_PROJECTS_DIR

    def discover(self) -> list[str]:
        """Top-level session transcripts (excludes nested subagent files)."""
        if not self.projects_dir.exists():
            return []
        return sorted(str(p) for p in self.projects_dir.glob("*/*.jsonl"))

    def read(self, source: str) -> tuple[list[Turn], FileMeta]:
        """Parse a transcript file into ordered Turns plus file metadata."""
        path = Path(source)
        base_id = path.stem
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            mtime = datetime.now().astimezone()

        turns: list[Turn] = []
        tool_names: dict[str, str] = {}
        cwd: str | None = None
        git_branch: str | None = None

        for raw in path.read_text(errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue

            if cwd is None and isinstance(entry.get("cwd"), str):
                cwd = entry["cwd"]
            if git_branch is None and isinstance(entry.get("gitBranch"), str):
                git_branch = entry["gitBranch"]

            etype = entry.get("type")
            if etype not in ("user", "assistant"):
                continue

            message = entry.get("message") or {}
            content = message.get("content")
            model = message.get("model")
            usage = message.get("usage") or {}
            # Bind per-line invariants now (avoids loop-variable closure issues).
            mk = partial(
                _make_turn,
                actor=self.actor,
                base_id=base_id,
                ts=_parse_ts(entry.get("timestamp")),
                uuid=entry.get("uuid"),
                parent=entry.get("parentUuid"),
            )

            line_turns = (
                _user_turns(content, tool_names, mk)
                if etype == "user"
                else _assistant_turns(content, model, usage, tool_names, mk)
            )
            turns.extend(line_turns)

        for index, turn in enumerate(turns):
            turn.seq = index
            turn.id = f"{base_id}-{index:06d}"

        return turns, FileMeta(
            session_id=base_id, cwd=cwd, git_branch=git_branch, mtime=mtime
        )

    def parse(self, source: str) -> Iterator[Turn]:
        """Collector-protocol entry point: yield normalized turns for one source."""
        turns, _meta = self.read(source)
        yield from turns


def _user_turns(content: object, tool_names: dict[str, str], mk: Any) -> list[Turn]:
    turns: list[Turn] = []
    if isinstance(content, str):
        if content.strip():
            turns.append(mk(role=Role.user, content=content))
        return turns
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                turns.append(mk(role=Role.user, content=block["text"]))
            elif btype == "tool_result":
                tid = block.get("tool_use_id")
                turns.append(
                    mk(
                        role=Role.tool,
                        tool_output=_stringify(block.get("content")),
                        error="tool_error" if block.get("is_error") else None,
                        tool_use_id=tid if isinstance(tid, str) else None,
                        tool_name=tool_names.get(tid) if isinstance(tid, str) else None,
                    )
                )
    return turns


def _assistant_turns(
    content: object,
    model: object,
    usage: dict[str, Any],
    tool_names: dict[str, str],
    mk: Any,
) -> list[Turn]:
    turns: list[Turn] = []
    blocks: list[Any] = content if isinstance(content, list) else []
    if isinstance(content, str) and content.strip():
        blocks = [{"type": "text", "text": content}]

    model_str = model if isinstance(model, str) else None
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and isinstance(block.get("text"), str) and block["text"].strip():
            turns.append(mk(role=Role.assistant, content=block["text"], model=model_str))
        elif btype == "tool_use":
            tid = block.get("id")
            name = block.get("name")
            if isinstance(tid, str) and isinstance(name, str):
                tool_names[tid] = name
            turns.append(
                mk(
                    role=Role.assistant,
                    tool_name=name if isinstance(name, str) else None,
                    tool_input=block.get("input") if isinstance(block.get("input"), dict) else None,
                    tool_use_id=tid if isinstance(tid, str) else None,
                    model=model_str,
                )
            )
        # thinking blocks are intentionally skipped

    if not turns and usage:
        turns.append(mk(role=Role.assistant, model=model_str))
    if turns and usage:
        first = turns[0]
        first.tokens_in = usage.get("input_tokens")
        first.tokens_out = usage.get("output_tokens")
        first.cache_creation_tokens = usage.get("cache_creation_input_tokens")
        first.cache_read_tokens = usage.get("cache_read_input_tokens")

    return turns


__all__ = ["ClaudeCodeCollector", "FileMeta", "DEFAULT_PROJECTS_DIR"]
