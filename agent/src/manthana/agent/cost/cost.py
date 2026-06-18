"""Per-session cost estimation from normalized Turns.

Re-expressed from affaan-m/ECC ``scripts/hooks/cost-tracker.js``
``sumUsageFromTranscript`` (MIT, 2026 Affaan Mustafa): sum input/output/cache
tokens across assistant turns, take the last seen model, and price via
``RATE_TABLE``. ECC summed by re-reading the JSONL transcript; here the tokens
already live on the parsed ``Turn``s, so we sum those.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from manthana.schemas import Turn

from .rates import get_rates, tier_of


@dataclass(frozen=True)
class CostBreakdown:
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    model: str | None
    tier: str | None
    usd: float


def estimate_cost(turns: Iterable[Turn]) -> CostBreakdown:
    """Sum token usage across turns and price it (USD)."""
    input_tokens = output_tokens = cache_write = cache_read = 0
    model: str | None = None
    for turn in turns:
        input_tokens += turn.tokens_in or 0
        output_tokens += turn.tokens_out or 0
        cache_write += turn.cache_creation_tokens or 0
        cache_read += turn.cache_read_tokens or 0
        if turn.model:
            model = turn.model
    rates = get_rates(model)
    usd = round(
        (input_tokens / 1e6) * rates["in"]
        + (output_tokens / 1e6) * rates["out"]
        + (cache_write / 1e6) * rates["cacheWrite"]
        + (cache_read / 1e6) * rates["cacheRead"],
        6,
    )
    return CostBreakdown(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        model=model,
        tier=tier_of(model),
        usd=usd,
    )


__all__ = ["CostBreakdown", "estimate_cost"]
