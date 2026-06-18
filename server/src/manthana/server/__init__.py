"""Manthana org server.

Self-hosted by the organization. Built out in the server phase: FastAPI
ingestion API, Postgres + pgvector, multi-tenant Org > Team > Actor (Project as a
cross-cutting tag), k-anonymity floor, action queue, and raw-transcript release
to an S3-compatible store.

LICENSING: this package is the ONLY AGPL-3.0-licensed component of Manthana
(everything else is Apache-2.0). Keeping the server in a separate distribution
(``manthana-server``) preserves the dual-license boundary from the spec: a SaaS
competitor cannot re-host the server without contributing back, while the client
tooling stays embeddable.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

__all__: list[str] = []
