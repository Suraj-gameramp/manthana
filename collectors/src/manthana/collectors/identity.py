"""Resolve the engineer ``actor`` identity for captured turns/sessions.

Order: ``$MANTHANA_ACTOR`` → global git ``user.email`` → OS username. The actor
is the engineer identity used across the local store and (later) the server
(decisions doc / architecture §8: actor = org email).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import getpass
import os
import subprocess

ACTOR_ENV = "MANTHANA_ACTOR"


def resolve_actor() -> str:
    env = os.environ.get(ACTOR_ENV)
    if env and env.strip():
        return env.strip()
    try:
        out = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001 - git may be absent; fall through
        pass
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"


__all__ = ["resolve_actor", "ACTOR_ENV"]
