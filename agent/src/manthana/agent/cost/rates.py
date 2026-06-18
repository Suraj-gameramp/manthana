"""Model cost rate table.

``RATE_TABLE`` is copied verbatim from affaan-m/ECC
``scripts/hooks/cost-tracker.js`` (MIT, 2026 Affaan Mustafa) — the per-1M-token
USD billing rates (cache creation ~1.25x input, cache read ~0.1x input). The
``get_rates`` model→tier resolution is re-expressed from ECC ``getRates``.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

# Copied verbatim from ECC cost-tracker.js (MIT, 2026 Affaan Mustafa):
#   const RATE_TABLE = {
#     haiku:  { in: 0.80,  out: 4.0,  cacheWrite: 1.00,  cacheRead: 0.08 },
#     sonnet: { in: 3.00,  out: 15.0, cacheWrite: 3.75,  cacheRead: 0.30 },
#     opus:   { in: 15.00, out: 75.0, cacheWrite: 18.75, cacheRead: 1.50 }
#   };
RATE_TABLE: dict[str, dict[str, float]] = {
    "haiku": {"in": 0.80, "out": 4.0, "cacheWrite": 1.00, "cacheRead": 0.08},
    "sonnet": {"in": 3.00, "out": 15.0, "cacheWrite": 3.75, "cacheRead": 0.30},
    "opus": {"in": 15.00, "out": 75.0, "cacheWrite": 18.75, "cacheRead": 1.50},
}


def get_rates(model: str | None) -> dict[str, float]:
    """Resolve a model id to its rate row (re-expressed from ECC getRates)."""
    m = (model or "").lower()
    if "haiku" in m:
        return RATE_TABLE["haiku"]
    if "opus" in m:
        return RATE_TABLE["opus"]
    return RATE_TABLE["sonnet"]


def tier_of(model: str | None) -> str | None:
    """Human tier label for a model id, or None if unrecognized."""
    m = (model or "").lower()
    if "haiku" in m:
        return "haiku"
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    return None


__all__ = ["RATE_TABLE", "get_rates", "tier_of"]
