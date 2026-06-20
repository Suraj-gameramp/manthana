"""Local dashboard (FastAPI + HTMX) — the employee control plane.

Read AND act, all from the browser (no terminal needed): view sessions,
compactions, and mined skills, and run capture / compact / release / mine / sync
from buttons. Server-rendered HTML + htmx, no build step. Localhost, single
employee, no auth (the employee owns their own store).

Actions use redirect-after-POST (303); tunables ride in the URL query string so
no python-multipart dependency is needed. The Work/Personal toggle stays htmx.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import html
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from manthana.agent.capture import ingest_all
from manthana.agent.compact import compact_session
from manthana.agent.cost import estimate_cost
from manthana.agent.llm import LLMProvider
from manthana.agent.skillminer import mine_personal, write_proposal
from manthana.agent.store import Store
from manthana.schemas import BaseCompaction, Mode, Session

_log = logging.getLogger(__name__)

_DEFAULT_SKILLS_DIR = Path.home() / ".claude" / "skills" / "personal"

_HTMX = '<script src="https://unpkg.com/htmx.org@2.0.3"></script>'
_STYLE = (
    "<style>body{font:14px system-ui;margin:2rem;max-width:1100px}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}"
    "th{background:#f5f5f5}a{color:#06c}nav a{margin-right:1rem}"
    ".personal{color:#a00;font-weight:600}.work{color:#070}"
    "form{display:inline}button{cursor:pointer;padding:3px 8px}"
    ".badge{padding:1px 6px;border-radius:4px;font-size:12px}"
    ".rel{background:#dfd;color:#060}.unrel{background:#eee;color:#666}"
    ".ok{color:#060}.warn{color:#a60}details summary{cursor:pointer}"
    ".bar{margin:0 0 1rem;padding:.6rem;background:#f7f7f7;border:1px solid #eee;border-radius:6px}"
    "pre{white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:8px}</style>"
)


def _e(value: object) -> str:
    return html.escape(str(value))


def _page(title: str, body: str, *, refresh: int = 0) -> str:
    # Auto-refresh (used by the Sessions page while a background compaction runs,
    # so "⏳ compacting…" flips to "✓ compacted" without a manual reload).
    refresh_tag = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh > 0 else ""
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>Manthana — {_e(title)}</title>"
        f"{refresh_tag}{_HTMX}{_STYLE}</head><body>"
        "<h1>Manthana</h1>"
        "<nav><a href='/'>Sessions</a><a href='/ask'>Ask</a>"
        "<a href='/compactions'>Compactions</a><a href='/skills'>Skills</a>"
        "<a href='/optimize'>Optimize</a><a href='/cost'>Cost</a>"
        "<a href='/actions'>Actions</a></nav>"
        f"{body}</body></html>"
    )


def _mode_cell(session: Session) -> str:
    other = Mode.work if session.mode is Mode.personal else Mode.personal
    cls = "personal" if session.mode is Mode.personal else "work"
    return (
        f"<span class='{cls}'>{_e(session.mode)}</span> "
        f"<button hx-post='/session/{_e(session.id)}/mode/{other.value}' "
        f"hx-target='#row-{_e(session.id)}' hx-swap='outerHTML'>→ {other.value}</button>"
    )


def _compact_cell(session: Session, compacted: set[str], compacting: set[str]) -> str:
    if session.id in compacting:
        return "<span class='warn'>⏳ compacting… <small>(refreshes)</small></span>"
    if session.id in compacted:
        return "<span class='ok'>✓ compacted</span>"
    return (
        f"<form method='post' action='/session/{_e(session.id)}/compact'>"
        "<button title='Runs your claude CLI — costs tokens, ~30-60s'>compact</button></form>"
    )


def _session_row(session: Session, compacted: set[str], compacting: set[str]) -> str:
    tags = ", ".join(f"{_e(k)}={_e(v)}" for k, v in session.tags.items()) or "—"
    return (
        f"<tr id='row-{_e(session.id)}'>"
        f"<td>{_e(session.id)}</td><td>{_e(session.project)}</td>"
        f"<td>{session.turn_count}</td><td>{tags}</td>"
        f"<td>{_mode_cell(session)}</td>"
        f"<td>{_compact_cell(session, compacted, compacting)}</td></tr>"
    )


def _compaction_row(c: BaseCompaction) -> str:
    badge = (
        "<span class='badge rel'>released</span>"
        if c.released
        else "<span class='badge unrel'>local</span>"
    )
    label = "unrelease" if c.released else "release"
    details = (
        f"<details><summary>{_e(c.task_intent[:80])}</summary>"
        f"<b>intent:</b> {_e(c.task_intent)}<br><b>approach:</b> {_e(c.approach)}</details>"
    )
    cost = f"${c.est_cost_usd:.4f}" if c.est_cost_usd is not None else "—"
    return (
        f"<tr><td>{_e(c.id)}</td><td>{_e(c.project)}</td><td>{_e(c.outcome)}</td>"
        f"<td>{_e(c.tier_used)}</td><td>{cost}</td><td>{badge}</td>"
        f"<td><form method='post' action='/compaction/{_e(c.id)}/release'>"
        f"<button>{label}</button></form></td><td>{details}</td></tr>"
    )


def _read_skill(skill_dir: Path) -> str:
    md = (skill_dir / "SKILL.md").read_text()
    name, description, _body = _parse_skill_md(md)
    meta = ""
    prov_path = skill_dir / "provenance.json"
    if prov_path.exists():
        try:
            prov = json.loads(prov_path.read_text())
            meta = (
                f"<small>sessions={_e(prov.get('session_count'))} · "
                f"contributors={_e(prov.get('contributor_count'))} · "
                f"cohesion={_e(prov.get('confidence'))} · "
                f"evidence={len(prov.get('evidence', []))}</small>"
            )
        except json.JSONDecodeError:
            meta = ""
    return (
        f"<div class='bar'><b>{_e(name)}</b> {meta}<br>{_e(description)}"
        f"<details><summary>SKILL.md</summary><pre>{_e(md)}</pre></details></div>"
    )


def _parse_skill_md(md: str) -> tuple[str, str, str]:
    name, description, body = "", "", md
    parts = md.split("---", 2)
    if len(parts) == 3:
        front, body = parts[1], parts[2]
        for line in front.splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
    return name, description, body


def create_app(
    store: Store,
    *,
    provider: LLMProvider | None = None,
    skills_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Manthana Dashboard")
    skills_path = skills_dir or _DEFAULT_SKILLS_DIR

    # Sessions whose compaction is running in a background thread (the claude call
    # is ~30-60s; the request returns immediately). Guarded by a lock since the
    # worker thread and request handlers both touch it.
    compacting: set[str] = set()
    compacting_lock = threading.Lock()

    def _run_compaction(session_id: str) -> None:
        try:
            compact_session(store, session_id, provider=provider)
        except Exception:
            # Background daemon thread: an uncaught exception here is invisible to
            # the request that started it, so log it explicitly (else a failed
            # compaction silently reverts to the "compact" button with no trace).
            _log.exception("background compaction failed for session %s", session_id)
        finally:
            with compacting_lock:
                compacting.discard(session_id)

    # ── Sessions ─────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        compacted = {c.session_id for c in store.list_compactions(limit=100_000)}
        with compacting_lock:
            in_progress = set(compacting)
        rows = "".join(
            _session_row(s, compacted, in_progress) for s in store.list_sessions(limit=200)
        )
        bar = (
            "<div class='bar'><form method='post' action='/capture'>"
            "<button>⤓ Capture transcripts</button></form> "
            "<small>ingest your ~/.claude sessions into the local store</small></div>"
        )
        table = (
            "<table><tr><th>session</th><th>project</th><th>turns</th>"
            "<th>tags</th><th>mode</th><th>compaction</th></tr>"
            f"{rows or '<tr><td colspan=6>no sessions yet — click Capture</td></tr>'}</table>"
        )
        # Poll every 4s only while something is compacting, then stop.
        return _page("Sessions", bar + table, refresh=4 if in_progress else 0)

    # ── Ask & Insights (self-query) ──────────────────────────────────────
    @app.get("/ask", response_class=HTMLResponse)
    def ask_page(question: str = "", since: str = "") -> str:
        # GET form (read-only query → no python-multipart). The structural panel
        # is token-free; a question runs the grounded `ask` (uses your model).
        from manthana.agent.insights import ask as run_ask
        from manthana.agent.insights import structural_insights

        s = structural_insights(store, since=since or None)
        projects = ", ".join(f"{_e(p)}={n}" for p, n in list(s.by_project.items())[:12]) or "—"
        outcomes = (
            f"<br>outcomes: {_e(s.by_outcome)}" if s.by_outcome else ""
        )
        cost_note = " (recent 300)" if s.cost_capped else ""
        panel = (
            f"<div class='bar'><b>Your work{(' · last ' + _e(since)) if since else ''}</b>: "
            f"{s.session_count} sessions, {s.compaction_count} compactions · "
            f"est. API-equivalent cost ~${s.est_cost_usd}{cost_note}"
            f"<br>projects: {projects}{outcomes}</div>"
        )
        form = (
            "<div class='bar'><form method='get' action='/ask'>"
            f"<input name='question' size='64' value='{_e(question)}' "
            "placeholder='ask about your sessions — e.g. what did I work on last week?'> "
            "<button>Ask</button></form>"
            "<small>grounded over your compactions; uses your model (claude)</small></div>"
        )
        answer = ""
        if question:
            result = run_ask(store, question, provider=provider)
            cites = ", ".join(_e(c) for c in result.citations) or "—"
            tag = "" if result.grounded else " <span class='warn'>(ungrounded)</span>"
            answer = (
                f"<h3>Answer{tag}</h3><pre>{_e(result.narrative)}</pre><p>sources: {cites}</p>"
            )
        return _page("Ask", panel + form + answer)

    # ── Optimize (headroom context compression) ──────────────────────────
    @app.get("/optimize", response_class=HTMLResponse)
    def optimize_page() -> str:
        from manthana.agent import optimize as opt

        if not opt.available():
            return _page(
                "Optimize",
                "<div class='bar warn'>headroom isn't installed. It compresses Claude "
                "Code context (60–95% fewer tokens).<br>Install: "
                '<code>pip install "headroom-ai[proxy,mcp]"</code> '
                "(or <code>uv sync --extra optimize</code>), then reload.</div>",
            )
        proxy = " ".join(opt.proxy_cmd())
        env = " ".join(f"{k}={v}" for k, v in opt.claude_env().items())
        setup = (
            "<div class='bar'><b>headroom installed ✓</b><br>"
            "One-time durable setup: <code>manthana optimize setup</code><br>"
            "Or run the proxy and point Claude Code at it:"
            f"<pre>{_e(proxy)}\n{_e(env)} claude</pre>"
            "<form method='post' action='/optimize/tune'>"
            "<button>⛁ Tune CLAUDE.md from my history</button></form>"
            "<small>headroom learn — mines past sessions into failure-avoidance "
            "context</small></div>"
        )
        s = opt.stats()
        if s.get("data"):
            body = f"<h3>Savings</h3><pre>{_e(json.dumps(s['data'], indent=2)[:2000])}</pre>"
        else:
            body = f"<p class='muted'>{_e(s.get('error', 'run the proxy to collect stats'))}</p>"
        return _page("Optimize", setup + body)

    @app.post("/optimize/tune")
    def optimize_tune() -> RedirectResponse:
        from manthana.agent import optimize as opt

        # `headroom learn` can take a while — run it off the request thread so the
        # dashboard stays responsive, and log the outcome (don't fail silently).
        def _run() -> None:
            try:
                result = opt.tune()
                _log.info("optimize tune: %s", "ok" if result.get("ok") else result)
            except Exception:
                _log.exception("optimize tune failed")

        threading.Thread(target=_run, daemon=True).start()
        return RedirectResponse(url="/optimize", status_code=303)

    @app.post("/capture")
    def capture() -> RedirectResponse:
        ingest_all(store)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/session/{session_id}/mode/{value}", response_class=HTMLResponse)
    def toggle_mode(session_id: str, value: str) -> str:
        try:
            store.set_session_mode(session_id, Mode(value))
        except ValueError:
            pass
        session = store.get_session(session_id)
        compacted = {c.session_id for c in store.list_compactions(limit=100_000)}
        with compacting_lock:
            in_progress = set(compacting)
        return (
            _session_row(session, compacted, in_progress)
            if session
            else "<tr><td>gone</td></tr>"
        )

    @app.post("/session/{session_id}/compact")
    def compact(session_id: str) -> RedirectResponse:
        # Run compaction off the request thread (the claude call blocks ~30-60s);
        # the Sessions page shows "compacting…" and auto-refreshes until it lands.
        with compacting_lock:
            start = session_id not in compacting
            if start:
                compacting.add(session_id)
        if start:
            threading.Thread(
                target=_run_compaction, args=(session_id,), daemon=True
            ).start()
        return RedirectResponse(url="/", status_code=303)

    # ── Compactions (review-before-sync inbox) ───────────────────────────
    @app.get("/compactions", response_class=HTMLResponse)
    def compactions() -> str:
        comps = store.list_compactions(limit=500)
        rows = "".join(_compaction_row(c) for c in comps)
        bar = (
            "<div class='bar'><form method='post' action='/sync'>"
            "<button>↥ Sync released</button></form> "
            "<small>push released compactions to the org server "
            "(needs MANTHANA_SERVER_URL + MANTHANA_TEAM_TOKEN)</small></div>"
        )
        table = (
            "<table><tr><th>id</th><th>project</th><th>outcome</th><th>tier</th>"
            "<th>cost</th><th>state</th><th></th><th>summary</th></tr>"
            f"{rows or '<tr><td colspan=8>no compactions — compact a session first</td></tr>'}"
            "</table>"
        )
        return _page("Compactions", bar + table)

    @app.post("/compaction/{compaction_id}/release")
    def release(compaction_id: str) -> RedirectResponse:
        comp = store.get_compaction(compaction_id)
        if comp is not None:
            now = datetime.now(UTC)
            store.mark_released(
                compaction_id,
                released=not comp.released,
                released_at=None if comp.released else now,
            )
        return RedirectResponse(url="/compactions", status_code=303)

    @app.post("/sync")
    def sync() -> Response:
        import os

        from manthana.agent.config import load_config
        from manthana.agent.sync_client import SyncClient

        config = load_config()
        base = os.environ.get("MANTHANA_SERVER_URL") or config.server_url
        token = os.environ.get("MANTHANA_TEAM_TOKEN") or config.team_token
        if not base or not token:
            return HTMLResponse(
                _page(
                    "Sync",
                    "<div class='bar warn'>Sync not configured. Set "
                    "<code>MANTHANA_SERVER_URL</code> and <code>MANTHANA_TEAM_TOKEN</code> "
                    "(or the <code>[server]</code> section of manthana.toml), then retry.</div>"
                    "<a href='/compactions'>← back</a>",
                )
            )
        client = SyncClient(base, token)
        try:
            client.sync(store)
        finally:
            client.close()
        return RedirectResponse(url="/compactions", status_code=303)

    # ── Skills ───────────────────────────────────────────────────────────
    @app.get("/skills", response_class=HTMLResponse)
    def skills() -> str:
        cards = ""
        if skills_path.exists():
            cards = "".join(
                _read_skill(d)
                for d in sorted(skills_path.iterdir())
                if (d / "SKILL.md").exists()
            )
        bar = (
            "<div class='bar'><form method='post' action='/skills/mine?threshold=0.6'>"
            "<button>⛏ Mine skills</button></form> "
            "<small>cluster recurring patterns across your compactions into SKILL.md "
            "(deterministic; no tokens)</small></div>"
        )
        return _page("Skills", bar + (cards or "<p>no skills mined yet — click Mine skills</p>"))

    @app.post("/skills/mine")
    def skills_mine(threshold: float = 0.6, min_sessions: int = 3) -> RedirectResponse:
        for proposal in mine_personal(store, min_sessions=min_sessions, threshold=threshold):
            write_proposal(proposal, skills_path)
        return RedirectResponse(url="/skills", status_code=303)

    # ── Cost ─────────────────────────────────────────────────────────────
    @app.get("/cost", response_class=HTMLResponse)
    def cost() -> str:
        total = 0.0
        rows = []
        for s in store.list_sessions(limit=200):
            breakdown = estimate_cost(store.get_turns(s.id))
            total += breakdown.usd
            rows.append(
                f"<tr><td>{_e(s.id)}</td><td>{_e(s.project)}</td>"
                f"<td>{_e(breakdown.tier)}</td><td>${breakdown.usd:.4f}</td></tr>"
            )
        table = (
            "<table><tr><th>session</th><th>project</th><th>tier</th><th>est. cost</th></tr>"
            f"{''.join(rows)}</table><p><b>Total: ${total:.4f}</b></p>"
        )
        return _page("Cost", table)

    # ── Actions audit ────────────────────────────────────────────────────
    @app.get("/actions", response_class=HTMLResponse)
    def actions() -> str:
        rows = "".join(
            f"<tr><td>{_e(a.fired_at)}</td><td>{_e(a.action_id)}</td>"
            f"<td>{_e(a.outcome)}</td><td>{_e(a.trigger_condition)}</td>"
            f"<td>{_e(a.actor)}</td></tr>"
            for a in store.list_audit(limit=200)
        )
        table = (
            "<table><tr><th>fired_at</th><th>action</th><th>outcome</th>"
            "<th>trigger</th><th>actor</th></tr>"
            f"{rows or '<tr><td colspan=5>no actions fired yet</td></tr>'}</table>"
        )
        return _page("Actions", table)

    return app


__all__ = ["create_app"]
