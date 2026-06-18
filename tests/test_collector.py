"""Claude Code collector + sessionization + capture-pipeline tests.

Built against a synthetic fixture faithful to the verified Claude Code JSONL
format, plus an optional smoke test over real local transcripts (skipped when
none exist) so parsing stays grounded in reality without committing real data.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import pytest
from manthana.agent.capture import ingest_file
from manthana.agent.store import Store
from manthana.collectors import ClaudeCodeCollector, register_builtin, registered
from manthana.collectors.claude_code import DEFAULT_PROJECTS_DIR
from manthana.schemas import Role, SessionEndReason, Surface

FIXTURE = str(Path(__file__).parent / "fixtures" / "claude_code" / "sample-session.jsonl")


def _collector() -> ClaudeCodeCollector:
    return ClaudeCodeCollector(actor="eng@example.com")


def test_parse_flattens_blocks_and_pairs_tools() -> None:
    turns, meta = _collector().read(FIXTURE)
    assert meta.session_id == "sample-session"
    assert meta.cwd == "/tmp/demo-proj"

    # meta line (file-history-snapshot) is skipped; 6 turns from 6 message lines:
    # u1 user, u2 (text + tool_use = 2), u3 tool_result, u4 text, u5 user, u6 text
    assert [t.role for t in turns] == [
        Role.user,
        Role.assistant,  # text
        Role.assistant,  # tool_use Read
        Role.tool,  # tool_result
        Role.assistant,
        Role.user,
        Role.assistant,
    ]
    # tool_use carries name/input; tool_result is paired back to the tool name
    tool_call = turns[2]
    assert tool_call.tool_name == "Read"
    assert tool_call.tool_input == {"file_path": "/tmp/demo-proj/parser.py"}
    tool_result = turns[3]
    assert tool_result.tool_use_id == "toolu_1"
    assert tool_result.tool_name == "Read"  # paired
    assert tool_result.error is None
    # ids and seq are contiguous
    assert [t.seq for t in turns] == list(range(len(turns)))
    assert turns[0].id == "sample-session-000000"


def test_usage_attached_once_per_line() -> None:
    turns, _ = _collector().read(FIXTURE)
    # u2's usage attaches to its FIRST emitted turn (the text), not the tool_use
    text_turn, tool_turn = turns[1], turns[2]
    assert text_turn.tokens_in == 100
    assert tool_turn.tokens_in is None  # not double-counted
    # total input tokens = 100 + 150 + 80 across the three assistant lines
    assert sum(t.tokens_in or 0 for t in turns) == 330


def test_sessionize_splits_on_gap_and_links_resume() -> None:
    store = Store.open_memory()
    result = ingest_file(store, FIXTURE, actor="eng@example.com")
    assert result.session_count == 2  # 45-min gap before u5 splits the session
    sessions = sorted(store.list_sessions(), key=lambda s: s.started_at)
    first, second = sessions
    assert first.id == "sample-session"
    assert first.ended_reason is SessionEndReason.gap
    assert second.id == "sample-session.2"
    assert second.resumed_from == "sample-session"
    assert second.ended_reason is SessionEndReason.open
    # project inferred from cwd basename (no git repo at /tmp/demo-proj)
    assert first.project == "demo-proj"
    assert first.repo_root is None
    assert first.surface is Surface.claude_code


def test_capture_persists_turns_in_order() -> None:
    store = Store.open_memory()
    ingest_file(store, FIXTURE, actor="eng@example.com")
    turns = store.get_turns("sample-session")
    assert [t.seq for t in turns] == list(range(len(turns)))
    assert turns[0].content == "Help me fix the failing test in parser.py"


def test_discover_excludes_subagents(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    proj = projects / "-tmp-demo"
    (proj / "abc123" / "subagents").mkdir(parents=True)
    (proj / "abc123.jsonl").write_text("{}\n")  # top-level session file
    (proj / "abc123" / "subagents" / "agent-x.jsonl").write_text("{}\n")  # nested
    found = ClaudeCodeCollector(actor="e", projects_dir=projects).discover()
    assert found == [str(proj / "abc123.jsonl")]


def test_register_builtin_populates_registry() -> None:
    register_builtin(actor="eng@example.com")
    assert "claude_code" in registered()
    assert "codex" in registered()


@pytest.mark.skipif(
    not DEFAULT_PROJECTS_DIR.exists() or not any(DEFAULT_PROJECTS_DIR.glob("*/*.jsonl")),
    reason="no real Claude Code transcripts on this machine",
)
def test_smoke_parse_real_transcript() -> None:
    """Parse one real transcript end-to-end without error (grounding check)."""
    collector = ClaudeCodeCollector(actor="eng@example.com")
    source = collector.discover()[0]
    turns, meta = collector.read(source)
    assert meta.session_id
    assert isinstance(turns, list)  # may be empty for a meta-only file, but must parse
