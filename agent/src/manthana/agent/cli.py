"""Manthana local-agent CLI (``manthana``).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import typer
from manthana.agent.actions import tag_all
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
def compact(session_id: str = typer.Argument(default="")) -> None:
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


@app.command()
def release(compaction_id: str = typer.Argument(default=...)) -> None:
    """Mark a compaction released — eligible to sync to the org server."""
    from datetime import UTC, datetime

    store = Store.open()
    ok = store.mark_released(compaction_id, released=True, released_at=datetime.now(UTC))
    typer.echo(f"released {compaction_id}" if ok else f"no such compaction: {compaction_id}")


@app.command()
def retag() -> None:
    """Run the auto-tag action over all sessions (writes tags to the store)."""
    store = Store.open()
    count = tag_all(store)
    typer.echo(f"dispatched auto-tag over sessions; {count} audit entries logged")


@app.command()
def dashboard(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the local dashboard (sessions, cost, action audit)."""
    import uvicorn
    from manthana.agent.dashboard import create_app

    uvicorn.run(create_app(Store.open()), host=host, port=port)


@app.command()
def sync(raw: bool = False) -> None:
    """Push released, non-personal compactions to the org server.

    Reads server URL + team token from MANTHANA_SERVER_URL / MANTHANA_TEAM_TOKEN
    (or the [server] section of manthana.toml). --raw also releases transcripts.
    """
    import os

    from manthana.agent.config import load_config
    from manthana.agent.sync_client import SyncClient

    config = load_config()
    base = os.environ.get("MANTHANA_SERVER_URL") or config.server_url
    token = os.environ.get("MANTHANA_TEAM_TOKEN") or config.team_token
    if not base or not token:
        typer.echo("set MANTHANA_SERVER_URL and MANTHANA_TEAM_TOKEN (or [server] in manthana.toml)")
        raise typer.Exit(code=1)

    client = SyncClient(base, token)
    try:
        result = client.sync(Store.open(), include_raw=raw)
    finally:
        client.close()
    typer.echo(
        f"synced {result.pushed} compaction(s); {result.skipped} already synced; "
        f"raw uploaded {result.raw_uploaded}"
    )


@app.command(name="mine-skills")
def mine_skills(min_sessions: int = 3, threshold: float = 0.75, write: bool = False) -> None:
    """Mine recurring patterns in your own compactions into proposed SKILL.md files.

    Drafts are deterministic by default (no token spend / works offline). Pass
    --write to draft them under ~/.claude/skills/personal/. Lower --threshold
    (e.g. 0.6) to cluster more loosely when using the offline embedder.
    """
    from pathlib import Path

    from manthana.agent.skillminer import mine_personal, write_proposal

    proposals = mine_personal(Store.open(), min_sessions=min_sessions, threshold=threshold)
    for p in proposals:
        prov = p.provenance
        typer.echo(
            f"{p.draft.name}  (sessions={prov.session_count}, cohesion={prov.confidence})"
        )
    if write and proposals:
        dest = Path.home() / ".claude" / "skills" / "personal"
        for p in proposals:
            write_proposal(p, dest)
        typer.echo(f"wrote {len(proposals)} skill(s) to {dest}")
    else:
        typer.echo(f"{len(proposals)} proposal(s); pass --write to draft them")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
