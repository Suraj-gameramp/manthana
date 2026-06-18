"""Cost estimation tests (verbatim ECC RATE_TABLE).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from manthana.agent.cost import estimate_cost, get_rates, tier_of
from manthana.schemas import Role, Turn


def _assistant(
    model: str,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> Turn:
    return Turn(
        id="t",
        session_id="s",
        actor="e",
        seq=0,
        role=Role.assistant,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )


def test_tier_and_rate_resolution() -> None:
    assert tier_of("claude-opus-4-8") == "opus"
    assert tier_of("claude-3-5-haiku") == "haiku"
    assert tier_of("claude-sonnet-4-6") == "sonnet"
    assert tier_of("mystery") is None
    assert get_rates("claude-opus-4-8")["in"] == 15.00
    assert get_rates("unknown-model") == get_rates("sonnet")  # defaults to sonnet


def test_estimate_cost_matches_rate_table() -> None:
    turns = [
        _assistant(
            "claude-opus-4-8",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
            cache_creation_tokens=1_000_000,
            cache_read_tokens=1_000_000,
        )
    ]
    cost = estimate_cost(turns)
    # opus: 15 + 75 + 18.75 + 1.5
    assert cost.usd == 110.25
    assert cost.tier == "opus"
    assert cost.input_tokens == 1_000_000


def test_estimate_cost_empty_is_zero() -> None:
    cost = estimate_cost([])
    assert cost.usd == 0.0
    assert cost.model is None
