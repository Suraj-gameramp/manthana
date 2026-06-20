"""Optimize (headroom) wrapper — command building, stats/tune via injected runner,
and the dashboard page (monkeypatched so it's hermetic whether or not headroom is
actually installed).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from manthana.agent import optimize as opt
from manthana.agent.dashboard import create_app
from manthana.agent.store import Store


def _present(_name: str) -> str:
    return "/usr/local/bin/headroom"


def _absent(_name: str) -> None:
    return None


# ── detection + command builders ────────────────────────────────────────────
def test_available_and_status() -> None:
    assert opt.available(_present) is True
    assert opt.available(_absent) is False
    st = opt.status(_absent)
    assert st.installed is False and "pip install" in st.hint


def test_command_builders() -> None:
    assert opt.setup_cmd() == ["headroom", "init", "claude", "--global"]
    assert opt.proxy_cmd(9000) == ["headroom", "proxy", "--port", "9000"]
    assert opt.claude_env(9000) == {"ANTHROPIC_BASE_URL": "http://localhost:9000"}
    assert opt.mcp_install_cmd() == ["headroom", "mcp", "install"]


# ── stats (parse headroom perf --format json) ───────────────────────────────
def test_stats_not_installed() -> None:
    assert opt.stats(which=_absent)["available"] is False


def test_stats_parses_json() -> None:
    def runner(_argv: list[str]) -> tuple[int, str, str]:
        return 0, '{"tokens_saved": 1234, "savings_pct": 0.9}', ""

    r = opt.stats(runner=runner, which=_present)
    assert r["data"]["tokens_saved"] == 1234


def test_stats_no_logs_yet() -> None:
    def runner(_argv: list[str]) -> tuple[int, str, str]:
        return 0, "not json", ""

    assert "no proxy logs" in opt.stats(runner=runner, which=_present)["error"]


def test_stats_error_on_nonzero() -> None:
    def runner(_argv: list[str]) -> tuple[int, str, str]:
        return 1, "", "boom"

    assert opt.stats(runner=runner, which=_present)["error"] == "boom"


def test_stats_rejects_oversized_output() -> None:
    # guard json.loads against a runaway blob (memory DoS)
    def runner(_argv: list[str]) -> tuple[int, str, str]:
        return 0, "x" * (opt._MAX_OUT + 1), ""

    assert opt.stats(runner=runner, which=_present)["error"] == "stats output too large"


# ── tune + setup (executes the right argv) ──────────────────────────────────
def test_tune_runs_learn_apply() -> None:
    seen: dict[str, list[str]] = {}

    def runner(argv: list[str]) -> tuple[int, str, str]:
        seen["argv"] = argv
        return 0, "wrote CLAUDE.md", ""

    r = opt.tune(runner=runner, which=_present)
    assert r["ok"] is True
    assert seen["argv"] == ["headroom", "learn", "--apply"]
    assert "CLAUDE.md" in r["output"]


def test_setup_runs_init_claude() -> None:
    seen: dict[str, list[str]] = {}

    def runner(argv: list[str]) -> tuple[int, str, str]:
        seen["argv"] = argv
        return 0, "ok", ""

    assert opt.setup(runner=runner, which=_present)["ok"] is True
    assert seen["argv"] == ["headroom", "init", "claude", "--global"]


def test_tune_not_installed() -> None:
    assert opt.tune(which=_absent)["available"] is False


# ── dashboard Optimize page (monkeypatched → hermetic) ──────────────────────
def test_dashboard_optimize_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opt, "available", lambda *a, **k: False)
    client = TestClient(create_app(Store.open_memory()))
    body = client.get("/optimize").text
    assert "isn't installed" in body and "pip install" in body


def test_dashboard_optimize_installed_shows_setup_and_savings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opt, "available", lambda *a, **k: True)
    monkeypatch.setattr(
        opt, "stats", lambda *a, **k: {"available": True, "data": {"tokens_saved": 999}}
    )
    client = TestClient(create_app(Store.open_memory()))
    body = client.get("/optimize").text
    assert "headroom installed" in body and "999" in body
    assert "Tune CLAUDE.md" in body
