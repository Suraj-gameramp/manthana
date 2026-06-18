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
    return Config(
        embeddings_model=embeddings.get("model", DEFAULT_EMBEDDINGS_MODEL),
        redact_secrets=bool(redaction.get("secrets", True)),
        redact_pii=bool(redaction.get("pii", True)),
        server_url=server.get("url"),
        team_token=server.get("token"),
    )


def build_redactor(config: Config | None = None):  # noqa: ANN201 - return type below
    """Construct a Redactor from config (kept here to avoid an import cycle)."""
    from .redaction import RedactionConfig, Redactor

    config = config or load_config()
    return Redactor(
        RedactionConfig(redact_secrets=config.redact_secrets, redact_pii=config.redact_pii)
    )


__all__ = ["Config", "load_config", "config_path", "build_redactor", "DEFAULT_EMBEDDINGS_MODEL"]
