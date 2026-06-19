"""Agent-side skill mining (personal scope).

Thin wrapper over the shared ``manthana.skills`` miner that wires in the agent's
``Redactor`` and reads the local store. Personal mining keeps contributor names
(the engineer's own data) and gates on recurrence across >=N distinct sessions.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from manthana.skills import SkillMiner, SkillProposal, mine_org, write_proposal
from manthana.skills.embed import Embedder
from manthana.skills.provider import LLMProvider

from .redaction import Redactor
from .store import Store


def mine_personal(
    store: Store,
    *,
    provider: LLMProvider | None = None,
    min_sessions: int = 3,
    embedder: Embedder | None = None,
) -> list[SkillProposal]:
    """Mine the engineer's OWN compactions into personal skill proposals."""
    compactions = store.list_compactions(limit=1_000_000)
    miner = SkillMiner(embedder=embedder, provider=provider, redactor=Redactor())
    return miner.mine(
        compactions, min_contributors=1, min_sessions=min_sessions, include_contributors=True
    )


__all__ = ["mine_personal", "write_proposal", "mine_org", "SkillMiner", "SkillProposal"]
