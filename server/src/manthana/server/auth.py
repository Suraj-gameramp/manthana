"""Authentication: team-scoped JWTs for agents, a static admin token for admins.

v1 mechanism (decisions doc): JWT + team-scoped tokens; admin bootstraps tokens.
An agent token carries org/team/actor; founder/admin endpoints use the configured
admin token.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"


@dataclass(frozen=True)
class TeamClaims:
    actor: str
    org_id: str
    team_id: str


class AuthError(Exception):
    """Raised on invalid/expired tokens."""


def issue_team_token(
    secret: str, *, org_id: str, team_id: str, actor: str, expires_days: int = 365
) -> str:
    payload = {
        "sub": actor,
        "org": org_id,
        "team": team_id,
        "scope": "agent",
        "exp": datetime.now(UTC) + timedelta(days=expires_days),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_team_token(secret: str, token: str) -> TeamClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "org", "team"], "verify_exp": True},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    if payload.get("scope") != "agent":
        raise AuthError("not an agent token")
    try:
        return TeamClaims(actor=payload["sub"], org_id=payload["org"], team_id=payload["team"])
    except KeyError as exc:
        raise AuthError(f"missing claim: {exc}") from exc


__all__ = ["TeamClaims", "AuthError", "issue_team_token", "verify_team_token", "ALGORITHM"]
