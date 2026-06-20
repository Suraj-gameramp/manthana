"""Agent config write/read + launchd plist content (Phase B onboarding).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from manthana.agent.cli import _watch_plist
from manthana.agent.config import Config, load_config, save_config


def test_config_save_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "manthana.toml"
    save_config(
        Config(server_url="https://s/", team_token="jwt123", actor="a@x.com", redact_pii=False),
        p,
    )
    loaded = load_config(p)
    assert loaded.server_url == "https://s/"
    assert loaded.team_token == "jwt123"
    assert loaded.actor == "a@x.com"
    assert loaded.redact_pii is False
    assert loaded.redact_secrets is True  # default preserved


def test_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "absent.toml")
    assert cfg.server_url is None and cfg.team_token is None and cfg.actor is None


def test_config_omits_empty_sections(tmp_path: Path) -> None:
    p = tmp_path / "m.toml"
    save_config(Config(), p)
    text = p.read_text()
    assert "[server]" not in text and "[identity]" not in text


def test_config_escapes_quotes_in_values(tmp_path: Path) -> None:
    p = tmp_path / "m.toml"
    save_config(Config(actor='weird"name'), p)
    assert load_config(p).actor == 'weird"name'


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_config_written_owner_only(tmp_path: Path) -> None:
    # The token lives here — it must not be world/group readable.
    p = tmp_path / "manthana.toml"
    save_config(Config(server_url="https://s", team_token="secret-jwt"), p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_watch_plist_includes_actor_env() -> None:
    pl = _watch_plist("/usr/local/bin/manthana", "alice@x.com")
    assert pl["ProgramArguments"] == ["/usr/local/bin/manthana", "watch", "--interval", "5"]
    assert pl["RunAtLoad"] is True and pl["KeepAlive"] is True
    assert pl["EnvironmentVariables"]["MANTHANA_ACTOR"] == "alice@x.com"  # type: ignore[index]


def test_watch_plist_no_actor_env_when_unset() -> None:
    pl = _watch_plist("/bin/manthana", None)
    assert "MANTHANA_ACTOR" not in pl["EnvironmentVariables"]  # type: ignore[operator]
