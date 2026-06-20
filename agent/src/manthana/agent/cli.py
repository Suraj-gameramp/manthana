"""Manthana local-agent CLI (``manthana``).

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from manthana.agent.actions import tag_all
from manthana.agent.capture import ingest_all
from manthana.agent.compact import compact_pending, compact_session
from manthana.agent.datahome import db_path, resolve_data_home
from manthana.agent.store import Store
from manthana.schemas import Mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from manthana.agent.sync_client import SyncClient


def _resolve_server() -> tuple[str | None, str | None]:
    """Server URL + team token: env wins over [server] in manthana.toml."""
    from manthana.agent.config import load_config

    config = load_config()
    base = os.environ.get("MANTHANA_SERVER_URL") or config.server_url
    token = os.environ.get("MANTHANA_TEAM_TOKEN") or config.team_token
    return base, token


def _sync_pushed(client: SyncClient) -> Callable[[Store], int]:
    """Adapt a SyncClient into the watcher's `sync_fn` (returns #pushed)."""

    def _fn(store: Store) -> int:
        return client.sync(store).pushed

    return _fn


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
def login(
    server: str = typer.Option(..., help="org server URL, e.g. https://manthana.yourco.com"),
    token: str = typer.Option(..., help="the team token from your admin (manthana-server onboard)"),
    actor: str = typer.Option("", help="your contributor identity, e.g. you@yourco.com"),
) -> None:
    """One-time: connect this agent to the org server (writes manthana.toml + verifies)."""
    import httpx
    from manthana.agent.config import load_config, save_config

    config = load_config()
    config.server_url = server.rstrip("/")
    config.team_token = token
    if actor:
        config.actor = actor
    path = save_config(config)
    typer.echo(f"wrote {path}")
    try:
        ok = httpx.get(f"{config.server_url}/healthz", timeout=5.0).status_code == 200
    except httpx.HTTPError as exc:
        typer.echo(f"saved, but {config.server_url} is not reachable yet: {exc}")
        return
    typer.echo(f"connected to {config.server_url} {'✓' if ok else '(unexpected response)'}")


@app.command()
def config() -> None:
    """Show the resolved agent config (token masked)."""
    from manthana.agent.config import config_path, load_config

    cfg = load_config()
    masked = (cfg.team_token[:8] + "…") if cfg.team_token else "(unset)"
    typer.echo(f"config:     {config_path()}")
    typer.echo(f"server_url: {cfg.server_url or '(unset)'}")
    typer.echo(f"team_token: {masked}")
    typer.echo(f"actor:      {cfg.actor or '(from MANTHANA_ACTOR / git / user)'}")
    typer.echo(f"redact:     secrets={cfg.redact_secrets} pii={cfg.redact_pii}")


@app.command()
def capture() -> None:
    """Ingest all local Claude Code transcripts into the store."""
    store = Store.open()
    results = ingest_all(store)
    sessions = sum(r.session_count for r in results)
    turns = sum(r.turn_count for r in results)
    typer.echo(f"ingested {len(results)} files -> {sessions} sessions, {turns} turns")


@app.command()
def watch(interval: float = 5.0, compact: bool = False, sync: bool = True) -> None:
    """Continuously ingest new/changed Claude Code transcripts (Ctrl-C to stop).

    Capture-only by default. When a server is configured, also auto-syncs released,
    redacted, non-personal compactions each cycle (--no-sync to disable). --compact
    also compacts pending Work sessions after each change (runs claude, costs tokens).
    """
    from manthana.agent.sync_client import SyncClient
    from manthana.agent.watcher import watch as run_watch

    store = Store.open()
    base, token = _resolve_server()
    client: SyncClient | None = None
    sync_fn: Callable[[Store], int] | None = None
    if sync and base and token:
        client = SyncClient(base, token)
        sync_fn = _sync_pushed(client)
        sync_state = "auto-sync on"
    else:
        sync_state = "auto-sync off (no server)" if sync else "auto-sync disabled"
    compact_state = "on" if compact else "off"
    typer.echo(
        f"watching ~/.claude/projects every {interval}s "
        f"(compact={compact_state}, {sync_state}) — Ctrl-C to stop"
    )
    try:
        run_watch(
            store, interval=interval, compact=compact, sync_fn=sync_fn, log=typer.echo
        )
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    finally:
        if client is not None:
            client.close()
        store.close()  # dispose the SQLite engine pool on exit


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
def sync(raw: bool = False, check: bool = False) -> None:
    """Push released, non-personal compactions to the org server.

    Reads server URL + team token from MANTHANA_SERVER_URL / MANTHANA_TEAM_TOKEN
    (or the [server] section of manthana.toml). --raw also releases transcripts.
    --check only verifies the server is reachable and the token is accepted (no push).
    """
    from manthana.agent.sync_client import SyncClient, SyncError

    base, token = _resolve_server()
    if not base or not token:
        typer.echo("not configured — run `manthana login --server <url> --token <jwt>` first")
        raise typer.Exit(code=1)

    if check:
        import httpx

        try:
            reachable = httpx.get(f"{base}/healthz", timeout=5.0).status_code == 200
        except httpx.HTTPError as exc:
            typer.echo(f"server unreachable: {exc}")
            raise typer.Exit(code=1) from exc
        client = SyncClient(base, token)
        try:
            client.push_compactions([])  # authed no-op: 200 if the token is accepted
        except SyncError as exc:
            typer.echo(f"token rejected by {base}: {exc}")
            raise typer.Exit(code=1) from exc
        finally:
            client.close()
        typer.echo(f"ok — {base} reachable (healthz={reachable}) and token accepted")
        return

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


_SERVICE_LABEL = "com.manthana.watch"


def _watch_plist(manthana_bin: str, actor: str | None) -> dict[str, object]:
    """launchd plist for the capture daemon (factored out for testability)."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if actor:
        env["MANTHANA_ACTOR"] = actor
    log = str(Path.home() / "Library" / "Logs" / "manthana-watch.log")
    return {
        "Label": _SERVICE_LABEL,
        "ProgramArguments": [manthana_bin, "watch", "--interval", "5"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": env,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


@app.command()
def service(action: str = typer.Argument("status")) -> None:
    """Run the capture daemon at login (macOS launchd): install | uninstall | status."""
    import platform
    import plistlib
    import shutil
    import subprocess

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{_SERVICE_LABEL}.plist"

    if platform.system() != "Darwin":
        typer.echo(
            "service is macOS-only. On Linux, create a `systemd --user` unit running "
            "`manthana watch` (see docs/onboarding.md)."
        )
        raise typer.Exit(code=1)

    def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["launchctl", *args], capture_output=True, text=True, check=False
            )
        except FileNotFoundError as exc:  # launchctl absent (shouldn't happen on macOS)
            typer.echo("`launchctl` not found — cannot manage the service")
            raise typer.Exit(code=1) from exc

    if action == "status":
        if not plist_path.exists():
            typer.echo("not installed")
            return
        state = "running" if _SERVICE_LABEL in _launchctl("list").stdout else "loaded (not running)"
        typer.echo(f"installed at {plist_path} — {state}")
        return

    if action == "install":
        from manthana.agent.config import load_config

        manthana_bin = shutil.which("manthana")
        if not manthana_bin:
            typer.echo("could not find the `manthana` executable on PATH")
            raise typer.Exit(code=1)
        actor = load_config().actor or os.environ.get("MANTHANA_ACTOR")
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        (Path.home() / "Library" / "Logs").mkdir(parents=True, exist_ok=True)
        with plist_path.open("wb") as fh:
            plistlib.dump(_watch_plist(manthana_bin, actor), fh)
        _launchctl("unload", str(plist_path))  # ignore: not loaded yet on first install
        loaded = _launchctl("load", "-w", str(plist_path))
        if loaded.returncode != 0:
            typer.echo(f"wrote {plist_path} but `launchctl load` failed: {loaded.stderr.strip()}")
            raise typer.Exit(code=1)
        typer.echo(f"installed + loaded {_SERVICE_LABEL} ({plist_path})")
        typer.echo("capture now runs at login; logs: ~/Library/Logs/manthana-watch.log")
        return

    if action == "uninstall":
        if not plist_path.exists():
            typer.echo("not installed")
            return
        _launchctl("unload", str(plist_path))
        plist_path.unlink(missing_ok=True)
        typer.echo(f"uninstalled {_SERVICE_LABEL}")
        return

    raise typer.BadParameter("action must be install | uninstall | status")


def _apply_identity_from_config() -> None:
    """Honor the configured contributor identity for every command (resolve_actor
    checks MANTHANA_ACTOR first), so capture/compact/sync attribute work correctly."""
    if not os.environ.get("MANTHANA_ACTOR"):
        from manthana.agent.config import load_config

        actor = load_config().actor
        if actor:
            os.environ["MANTHANA_ACTOR"] = actor


def main() -> None:
    """Console-script entry point."""
    _apply_identity_from_config()
    app()


if __name__ == "__main__":
    main()
