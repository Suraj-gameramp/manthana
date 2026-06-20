"""Agent configuration from ``$MANTHANA_DATA_HOME/manthana.toml`` (optional).

Returns sensible defaults when no config file exists. Currently covers the
embeddings model (decisions doc default) and redaction toggles; extended as more
of the agent becomes configurable.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .datahome import resolve_data_home

DEFAULT_EMBEDDINGS_MODEL = "BAAI/bge-large-en-v1.5"
CONFIG_FILENAME = "manthana.toml"


@dataclass
class Config:
    embeddings_model: str = DEFAULT_EMBEDDINGS_MODEL
    redact_secrets: bool = True
    redact_pii: bool = True
    server_url: str | None = None
    team_token: str | None = None
    actor: str | None = None  # contributor identity ([identity].actor); overrides git/user


def config_path() -> Path:
    return resolve_data_home() / CONFIG_FILENAME


def load_config(path: Path | None = None) -> Config:
    target = path or config_path()
    if not target.exists():
        return Config()
    data = tomllib.loads(target.read_text())
    embeddings = data.get("embeddings", {})
    redaction = data.get("redaction", {})
    server = data.get("server", {})
    identity = data.get("identity", {})
    return Config(
        embeddings_model=embeddings.get("model", DEFAULT_EMBEDDINGS_MODEL),
        redact_secrets=bool(redaction.get("secrets", True)),
        redact_pii=bool(redaction.get("pii", True)),
        server_url=server.get("url"),
        team_token=server.get("token"),
        actor=identity.get("actor"),
    )


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_config(config: Config, path: Path | None = None) -> Path:
    """Serialize ``config`` to ``manthana.toml`` (managed by ``manthana login``;
    the file stays hand-editable but comments are not round-tripped)."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Manthana agent config — managed by `manthana login`; also hand-editable.",
        "",
        "[embeddings]",
        f"model = {_toml_str(config.embeddings_model)}",
        "",
        "[redaction]",
        f"secrets = {str(config.redact_secrets).lower()}",
        f"pii = {str(config.redact_pii).lower()}",
    ]
    if config.server_url or config.team_token:
        lines.append("")
        lines.append("[server]")
        if config.server_url:
            lines.append(f"url = {_toml_str(config.server_url)}")
        if config.team_token:
            lines.append(f"token = {_toml_str(config.team_token)}")
    if config.actor:
        lines += ["", "[identity]", f"actor = {_toml_str(config.actor)}"]
    target.write_text("\n".join(lines) + "\n")
    # Holds the team JWT — keep it owner-only (best-effort; no-op on filesystems
    # without POSIX perms, e.g. some Windows setups).
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def build_redactor(config: Config | None = None):  # noqa: ANN201 - return type below
    """Construct a Redactor from config (kept here to avoid an import cycle)."""
    from .redaction import RedactionConfig, Redactor

    config = config or load_config()
    return Redactor(
        RedactionConfig(redact_secrets=config.redact_secrets, redact_pii=config.redact_pii)
    )


__all__ = [
    "Config",
    "load_config",
    "save_config",
    "config_path",
    "build_redactor",
    "DEFAULT_EMBEDDINGS_MODEL",
]
