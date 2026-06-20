"""Optimize — integrate **headroom** (the context-compression layer) so an engineer
runs Claude Code with far fewer tokens.

headroom is an OPTIONAL extra (`pip install "manthana[optimize]"`, i.e. headroom-ai).
This is a thin wrapper over its CLI: detect it, build the setup/proxy commands,
surface savings stats, and tune CLAUDE.md from real history. If headroom isn't
installed, every entry point degrades to an install hint (never a crash) — the same
posture as the sync-not-configured path.

Real headroom 0.26 surface used: `headroom init claude` (durable Claude Code
integration), `headroom proxy --port N` (+ ANTHROPIC_BASE_URL), `headroom mcp
install`, `headroom perf --format json` (savings), `headroom learn --apply` (tune).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

HEADROOM = "headroom"
INSTALL_HINT = 'headroom not installed — run: pip install "headroom-ai[proxy,mcp]"'
DEFAULT_PORT = 8787
_TIMEOUT_S = 180  # bound any headroom call (learn can be slow); never hang the caller
_MAX_OUT = 5_000_000  # guard json.loads against a runaway output (memory DoS)

# A runner takes argv → (returncode, stdout, stderr); injected in tests.
Runner = Callable[[list[str]], tuple[int, str, str]]
Which = Callable[[str], str | None]


def _subprocess_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - argv is constants + an int port, no shell
            argv, capture_output=True, text=True, check=False, timeout=_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"headroom timed out after {_TIMEOUT_S}s"
    return proc.returncode, proc.stdout, proc.stderr


def available(which: Which = shutil.which) -> bool:
    return which(HEADROOM) is not None


# ── command builders (proxy is long-running → we print, never block the CLI) ──
def setup_cmd(*, global_: bool = True) -> list[str]:
    cmd = [HEADROOM, "init", "claude"]
    if global_:
        cmd.append("--global")
    return cmd


def proxy_cmd(port: int = DEFAULT_PORT) -> list[str]:
    return [HEADROOM, "proxy", "--port", str(port)]


def claude_env(port: int = DEFAULT_PORT) -> dict[str, str]:
    """Env that points Claude Code at the running proxy."""
    return {"ANTHROPIC_BASE_URL": f"http://localhost:{port}"}


def mcp_install_cmd() -> list[str]:
    return [HEADROOM, "mcp", "install"]


@dataclass
class OptimizeStatus:
    installed: bool
    hint: str


def status(which: Which = shutil.which) -> OptimizeStatus:
    inst = available(which)
    return OptimizeStatus(installed=inst, hint="" if inst else INSTALL_HINT)


# ── executing helpers (one-shots; injectable runner) ─────────────────────────
def setup(
    *, global_: bool = True, runner: Runner = _subprocess_runner, which: Which = shutil.which
) -> dict[str, Any]:
    """Run `headroom init claude` — durable Claude Code integration."""
    if not available(which):
        return {"available": False, "hint": INSTALL_HINT}
    code, out, err = runner(setup_cmd(global_=global_))
    return {"available": True, "ok": code == 0, "output": (out or err).strip()[:1000]}


def mcp_install(
    *, runner: Runner = _subprocess_runner, which: Which = shutil.which
) -> dict[str, Any]:
    if not available(which):
        return {"available": False, "hint": INSTALL_HINT}
    code, out, err = runner(mcp_install_cmd())
    return {"available": True, "ok": code == 0, "output": (out or err).strip()[:1000]}


def stats(*, runner: Runner = _subprocess_runner, which: Which = shutil.which) -> dict[str, Any]:
    """Parsed `headroom perf --format json` (token savings, cache hits)."""
    if not available(which):
        return {"available": False, "hint": INSTALL_HINT}
    code, out, err = runner([HEADROOM, "perf", "--format", "json"])
    if code != 0:
        return {"available": True, "error": (err or out or "perf failed").strip()[:300]}
    if len(out) > _MAX_OUT:  # don't json.loads a runaway blob
        return {"available": True, "error": "stats output too large"}
    try:
        return {"available": True, "data": json.loads(out)}
    except json.JSONDecodeError:
        return {"available": True, "error": "no proxy logs yet — run the proxy first"}


def tune(
    *, apply: bool = True, runner: Runner = _subprocess_runner, which: Which = shutil.which
) -> dict[str, Any]:
    """`headroom learn [--apply]` — mine your history into CLAUDE.md context."""
    if not available(which):
        return {"available": False, "hint": INSTALL_HINT}
    cmd = [HEADROOM, "learn"]
    if apply:
        cmd.append("--apply")
    code, out, err = runner(cmd)
    return {"available": True, "ok": code == 0, "output": (out or err).strip()[:1000]}


__all__ = [
    "available", "status", "setup", "setup_cmd", "proxy_cmd", "claude_env",
    "mcp_install", "mcp_install_cmd", "stats", "tune",
    "OptimizeStatus", "INSTALL_HINT", "DEFAULT_PORT",
]
