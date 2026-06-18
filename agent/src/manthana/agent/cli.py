"""Manthana local-agent CLI (``manthana``).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import typer
from manthana.agent.capture import ingest_all
from manthana.agent.compact import compact_pending, compact_session
from manthana.agent.datahome import db_path, resolve_data_home
from manthana.agent.store import Store
from manthana.schemas import Mode

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


@app.command()
def capture() -> None:
    """Ingest all local Claude Code transcripts into the store."""
    store = Store.open()
    results = ingest_all(store)
    sessions = sum(r.session_count for r in results)
    turns = sum(r.turn_count for r in results)
    typer.echo(f"ingested {len(results)} files -> {sessions} sessions, {turns} turns")


@app.command()
def sessions(limit: int = 20) -> None:
    """List captured sessions (most recent first)."""
    store = Store.open()
    for s in store.list_sessions(limit=limit):
        started = s.started_at.strftime("%Y-%m-%d %H:%M")
        typer.echo(
            f"{s.id}  [{s.mode}]  {s.surface}  {s.project}  turns={s.turn_count}  {started}"
        )


@app.command()
def mode(session_id: str, value: str) -> None:
    """Set a session's mode: work | personal. Personal-mode sessions never sync."""
    try:
        new_mode = Mode(value)
    except ValueError as exc:
        raise typer.BadParameter("mode must be 'work' or 'personal'") from exc
    store = Store.open()
    ok = store.set_session_mode(session_id, new_mode)
    typer.echo(f"{session_id} -> {new_mode}" if ok else f"no such session: {session_id}")


@app.command()
def compact(session_id: str = "") -> None:
    """Compact a session (or all pending Work sessions if no id is given).

    Uses the engineer's own model access (claude -p / codex exec).
    """
    store = Store.open()
    if session_id:
        result = compact_session(store, session_id)
        typer.echo(
            f"{result.id}: {result.outcome} (${result.est_cost_usd}, {result.tier_used})"
            if result
            else f"no such session: {session_id}"
        )
        return
    results = compact_pending(store)
    typer.echo(f"compacted {len(results)} pending session(s)")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
