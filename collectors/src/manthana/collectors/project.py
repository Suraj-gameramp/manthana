"""Project inference from a working directory.

Decisions doc (capture): ``git rev-parse --show-toplevel`` with a cwd-basename
fallback; no per-project ``manthana init`` required.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def infer_project(cwd: str | None) -> tuple[str, str | None]:
    """Return ``(project_name, repo_root)`` for a working directory.

    ``repo_root`` is the git toplevel if ``cwd`` is inside a repo that still
    exists; otherwise it is ``None`` and the project name falls back to the cwd
    basename. A missing/old cwd is tolerated (returns its basename).
    """
    if not cwd:
        return ("unknown", None)
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            root = out.stdout.strip()
            return (Path(root).name, root)
    except Exception:  # noqa: BLE001 - git absent or cwd gone; fall back
        pass
    return (Path(cwd).name or "unknown", None)


__all__ = ["infer_project"]
