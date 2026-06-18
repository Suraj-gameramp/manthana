"""The single sync chokepoint. ALL data leaving the laptop passes through here.

Personal-mode sessions never leave the laptop — this is the trust-contract
invariant the decisions doc requires to be enforced by a dedicated test from
commit one (``tests/test_personal_mode_invariant.py``). Any future sync /
ingest / action-dispatch code that releases data to the org MUST route through
``eligible_for_sync``; do not add a bypass.

v1 implements the *gate*, not the transport. The transport (ingestion client,
raw-transcript upload) lands in later phases and calls this function.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from manthana.schemas import BaseCompaction, Mode, Session


def session_is_syncable(session: Session) -> bool:
    """A session may sync only if it is NOT personal mode.

    This is the hard invariant. It deliberately ignores every other signal: a
    personal session is never syncable regardless of release state or consent.
    """
    return session.mode is not Mode.personal


def eligible_for_sync(
    compactions: Iterable[BaseCompaction],
    sessions_by_id: Mapping[str, Session],
) -> list[BaseCompaction]:
    """Return only the compactions cleared to leave the laptop.

    Rules (v1):
      1. The owning session must NOT be personal mode (hard invariant).
      2. The compaction must be explicitly released (``released=True``).
      3. An unknown owning session fails closed (excluded).
    """
    out: list[BaseCompaction] = []
    for compaction in compactions:
        session = sessions_by_id.get(compaction.session_id)
        if session is None:
            continue  # fail closed: never sync something we can't classify
        if not session_is_syncable(session):
            continue  # personal-mode invariant
        if not compaction.released:
            continue  # compactions upload only on explicit release
        out.append(compaction)
    return out


__all__ = ["session_is_syncable", "eligible_for_sync"]
