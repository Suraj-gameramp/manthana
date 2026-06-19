"""Founder web console (server-rendered HTML + htmx).

A browser GUI for the org side — founder natural-language query, org/team overview,
and org skill mining — beyond the Swagger ``/docs`` page. Org-wide data, so it is
gated by a cookie-based admin login (``hmac.compare_digest`` vs the configured
admin token; httponly cookie). Self-hosted, single-admin for v1.

NOTE: like ``app.py``, this module intentionally does NOT use ``from __future__
import annotations`` — FastAPI must resolve the ``Form``/``Cookie`` parameters in
these closure-scoped route functions at runtime, which stringized annotations
would break.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

import hmac
import html
from typing import Annotated

from fastapi import Cookie, FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from manthana.skills import mine_org

from .config import ServerConfig
from .founder import run_query
from .llm import LLMProvider
from .store import ServerStore

COOKIE = "manthana_admin"

_STYLE = (
    "<style>body{font:14px system-ui;margin:2rem;max-width:1000px}"
    "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:6px 8px;"
    "text-align:left}th{background:#f5f5f5}button{cursor:pointer;padding:4px 10px}"
    "textarea,select,input{font:inherit;padding:4px}form{display:inline}"
    ".bar{margin:0 0 1rem;padding:.6rem;background:#f7f7f7;border:1px solid #eee;border-radius:6px}"
    ".warn{color:#a60}.muted{color:#666}pre{white-space:pre-wrap;background:#fafafa;"
    "border:1px solid #eee;padding:8px}nav a{margin-right:1rem}</style>"
)


def _e(value: object) -> str:
    return html.escape(str(value))


def _page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>Manthana — {title}</title>"
        f"{_STYLE}</head><body><h1>Manthana — Founder Console</h1>"
        "<nav><a href='/ui'>Console</a><a href='/ui/logout'>Log out</a>"
        "<a href='/docs'>API</a></nav>"
        f"{body}</body></html>"
    )


def _login_page(error: bool = False) -> str:
    msg = "<p class='warn'>Invalid admin token.</p>" if error else ""
    return _page(
        "Login",
        f"{msg}<form method='post' action='/ui/login'>"
        "<p>Admin token: <input type='password' name='token' autofocus></p>"
        "<button>Sign in</button></form>",
    )


def mount_ui(
    app: FastAPI, config: ServerConfig, store: ServerStore, provider: LLMProvider
) -> None:
    def _authed(cookie: str) -> bool:
        return bool(cookie) and hmac.compare_digest(cookie, config.admin_token)

    @app.get("/ui/login", response_class=HTMLResponse)
    def login_form() -> str:
        return _login_page()

    @app.post("/ui/login")
    def login(token: Annotated[str, Form()] = "") -> Response:
        if not hmac.compare_digest(token, config.admin_token):
            return HTMLResponse(_login_page(error=True), status_code=401)
        resp = RedirectResponse(url="/ui", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax")
        return resp

    @app.get("/ui/logout")
    def logout() -> Response:
        resp = RedirectResponse(url="/ui/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/ui", response_class=HTMLResponse)
    def console(manthana_admin: Annotated[str, Cookie()] = "") -> Response:
        if not _authed(manthana_admin):
            return RedirectResponse(url="/ui/login", status_code=303)
        orgs = store.list_orgs()
        options = "".join(f"<option value='{_e(o.id)}'>{_e(o.name)}</option>" for o in orgs)
        query_form = (
            "<div class='bar'><form method='post' action='/ui/query'>"
            f"<select name='org_id'>{options or '<option>—</option>'}</select> "
            "<input name='query' size='50' placeholder='what has the team been working on?'> "
            "<button>Ask</button></form></div>"
        )
        rows = []
        for o in orgs:
            teams = len(store.list_teams(o.id))
            comps = store.count_compactions(o.id)
            pending = len(store.list_queue(o.id))
            rows.append(
                f"<tr><td>{_e(o.name)} <span class='muted'>({_e(o.id)})</span></td>"
                f"<td>{teams}</td><td>{comps}</td><td>{pending}</td>"
                f"<td><form method='post' action='/ui/mine'>"
                f"<input type='hidden' name='org_id' value='{_e(o.id)}'>"
                "<button>Mine org skills</button></form></td></tr>"
            )
        table = (
            "<table><tr><th>org</th><th>teams</th><th>compactions</th>"
            "<th>pending skills</th><th></th></tr>"
            f"{''.join(rows) or '<tr><td colspan=5>no orgs yet</td></tr>'}</table>"
        )
        return HTMLResponse(_page("Console", query_form + table))

    @app.post("/ui/query", response_class=HTMLResponse)
    def ui_query(
        org_id: Annotated[str, Form()],
        query: Annotated[str, Form()],
        manthana_admin: Annotated[str, Cookie()] = "",
    ) -> Response:
        if not _authed(manthana_admin):
            return RedirectResponse(url="/ui/login", status_code=303)
        result = run_query(store, config, org_id=org_id, query=query, provider=provider)
        if result.rollup is None:
            roll = "<p class='warn'>insufficient data (k-anonymity floor not met)</p>"
        else:
            r = result.rollup
            roll = (
                f"<p>sessions={r.session_count} · contributors={r.distinct_contributors} · "
                f"cost=${r.total_cost_usd:.4f}</p>"
                f"<p>by project: {_e(r.by_project)}<br>by outcome: {_e(r.by_outcome)}</p>"
            )
        cites = ", ".join(_e(c) for c in result.citations) or "—"
        body = (
            f"<p class='muted'>query: {_e(query)} · org: {_e(org_id)}</p>{roll}"
            f"<h3>Narrative</h3><pre>{_e(result.narrative)}</pre>"
            f"<p>citations: {cites}</p><p><a href='/ui'>← back</a></p>"
        )
        return HTMLResponse(_page("Query", body))

    @app.post("/ui/mine")
    def ui_mine(
        org_id: Annotated[str, Form()], manthana_admin: Annotated[str, Cookie()] = ""
    ) -> Response:
        if not _authed(manthana_admin):
            return RedirectResponse(url="/ui/login", status_code=303)
        compactions = store.query_compactions(org_id=org_id, limit=100_000)
        for proposal in mine_org(compactions, provider=provider):
            store.enqueue_action(
                action_id="auto_draft_org_skill",
                org_id=org_id,
                payload={
                    "name": proposal.draft.name,
                    "description": proposal.draft.description,
                    "skill_md": proposal.skill_md,
                    "contributor_count": proposal.provenance.contributor_count,
                },
            )
        return RedirectResponse(url="/ui", status_code=303)


__all__ = ["mount_ui", "COOKIE"]
