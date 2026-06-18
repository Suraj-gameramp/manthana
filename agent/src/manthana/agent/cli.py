"""Manthana local-agent CLI (``manthana``).

v1 foundation provides introspection commands; capture/compact/dashboard
sub-commands are wired in later phases.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import typer
from manthana.agent.datahome import db_path, resolve_data_home

app = typer.Typer(
    help="Manthana — local-first capture of AI coding interactions.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print the installed Manthana version."""
    try:
        typer.echo(_pkg_version("manthana"))
    except PackageNotFoundError:
        typer.echo("0+unknown")


@app.command()
def datahome() -> None:
    """Show the resolved MANTHANA_DATA_HOME and database path."""
    typer.echo(f"data_home: {resolve_data_home()}")
    typer.echo(f"db_path:   {db_path()}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
