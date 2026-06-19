"""Server LLM providers: AnthropicProvider + make_provider selection.

Fully hermetic — the AnthropicProvider tests inject a fake Messages client, so
no `anthropic` SDK install and no ANTHROPIC_API_KEY are needed. The integration
test drives the real founder pipeline through a fake-backed AnthropicProvider to
prove a real provider yields a grounded, cited narrative (vs the mock's
"insufficient data").

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from manthana.schemas import EngineeringCompaction, Outcome, Surface
from manthana.server import ServerConfig, ServerStore
from manthana.server.founder import run_query
from manthana.server.llm import AnthropicProvider, MockProvider, make_provider

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


# ── fake Anthropic client (mimics messages.create -> message.content blocks) ──
class _Block:
    def __init__(self, text: str | None, kind: str = "text") -> None:
        self.type = kind
        if text is not None:
            self.text = text


class _Message:
    def __init__(self, blocks: list[_Block]) -> None:
        self.content = blocks


class _Messages:
    def __init__(self, blocks: list[_Block]) -> None:
        self._blocks = blocks
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        return _Message(self._blocks)


class _Client:
    def __init__(self, blocks: list[_Block]) -> None:
        self.messages = _Messages(blocks)


# ── AnthropicProvider ───────────────────────────────────────────────────────
def test_anthropic_provider_concatenates_text_blocks_and_passes_params() -> None:
    client = _Client([_Block("hello "), _Block("[c0]")])
    p = AnthropicProvider(model="claude-x", max_tokens=42, client=client)
    assert p.name == "anthropic"
    assert p.complete("prompt") == "hello [c0]"
    call = client.messages.calls[0]
    assert call["model"] == "claude-x"
    assert call["max_tokens"] == 42
    assert call["messages"] == [{"role": "user", "content": "prompt"}]


def test_anthropic_provider_ignores_non_text_blocks() -> None:
    # tool_use / thinking blocks have no .text and must be skipped, not crash.
    client = _Client([_Block(None, kind="tool_use"), _Block("real answer")])
    p = AnthropicProvider(model="m", client=client)
    assert p.complete("x") == "real answer"


def test_anthropic_provider_survives_text_block_missing_text_attr() -> None:
    # A malformed block typed "text" but without a .text attribute must not crash.
    client = _Client([_Block(None, kind="text"), _Block("ok")])
    p = AnthropicProvider(model="m", client=client)
    assert p.complete("x") == "ok"


# ── make_provider selection ─────────────────────────────────────────────────
def _cfg(**kw: Any) -> ServerConfig:
    return ServerConfig(jwt_secret="x" * 40, admin_token="adm", **kw)


def test_make_provider_defaults_to_mock() -> None:
    provider = make_provider(_cfg())
    assert isinstance(provider, MockProvider)
    assert provider.name == "mock"


def test_make_provider_selects_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    import manthana.server.llm as llm

    captured: dict[str, Any] = {}

    class _Stub:
        name = "anthropic"

        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(llm, "AnthropicProvider", _Stub)
    cfg = _cfg(llm_provider="anthropic", llm_model="claude-z", llm_max_tokens=7)
    provider = llm.make_provider(cfg)
    assert provider.name == "anthropic"
    assert captured == {"model": "claude-z", "max_tokens": 7}


def test_invalid_llm_provider_rejected() -> None:
    with pytest.raises(ValueError):
        _cfg(llm_provider="gpt")


def test_config_rejects_out_of_range_numeric_bounds() -> None:
    with pytest.raises(ValueError):
        _cfg(llm_max_tokens=0)  # empty narrative
    with pytest.raises(ValueError):
        _cfg(llm_max_tokens=10_000_000)  # runaway cost typo
    with pytest.raises(ValueError):
        _cfg(k_anon_floor=0)  # would disable the privacy floor


# ── integration: a real provider produces a grounded, cited narrative ────────
def _comp(cid: str, actor: str) -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=cid,
        actor=actor,
        surface=Surface.claude_code,
        project="scribe",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent=f"intent {cid}",
        approach="a",
        outcome=Outcome.success,
        est_cost_usd=0.5,
        tier_used="opus",
        released=True,
    )


class _BoomProvider:
    """Raises on every call — stands in for a rate-limited / down Anthropic API."""

    name = "boom"

    def complete(self, prompt: str) -> str:
        raise RuntimeError("api unavailable: sk-should-never-reach-client")


def test_run_query_degrades_gracefully_on_provider_error() -> None:
    # A provider exception must NOT 500 the endpoint or leak the SDK exception —
    # it degrades to "insufficient data" (rollup kept, narrative withheld).
    config = _cfg(k_anon_floor=1)
    store = ServerStore.open("sqlite://")
    store.create_org("o1", "Acme")
    store.ingest_compaction(_comp("c0", "e@x.com"), org_id="o1", team_id="t1")
    result = run_query(store, config, org_id="o1", query="what shipped?", provider=_BoomProvider())
    assert result.insufficient_data is True
    assert result.narrative == "insufficient data"
    assert result.citations == []


def test_founder_query_grounded_with_anthropic_provider() -> None:
    config = _cfg(k_anon_floor=1)
    store = ServerStore.open("sqlite://")
    store.create_org("o1", "Acme")
    store.ingest_compaction(_comp("c0", "e@x.com"), org_id="o1", team_id="t1")
    # The fake returns a citing narrative for the narrative call (and "{}"-free
    # text for parse → empty filter → all rows), so grounding succeeds.
    provider = AnthropicProvider(
        model="m", client=_Client([_Block("Team shipped the scribe work [c0].")])
    )
    result = run_query(store, config, org_id="o1", query="what shipped?", provider=provider)
    assert result.insufficient_data is False
    assert result.citations == ["c0"]
    assert "[c0]" in result.narrative
