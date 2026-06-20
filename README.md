# Manthana

Open-source, local-first platform that captures every AI coding interaction
across an organization, distills each session into a typed **compaction**, and
gives founders grounded, citation-backed visibility — while the employee owns
the local store and the org sees only what is explicitly released.

**New to the codebase?** Start with the **[Technical Report](docs/report/)** — a
diagram-rich tour (overview, architecture, dataflow, sequence diagrams, trust
model, decisions, roadmap). The full spec is under [`spec/`](spec/) and the
chronological architecture log in
[`spec/manthana-architecture.md`](spec/manthana-architecture.md).

## Status

v1 in progress, built as a vertical slice. Current foundation:

- Monorepo (`uv` workspace) with four packages under the `manthana` namespace.
- All data schemas (Pydantic v2) with a mirrored JSON Schema export.
- The personal-mode sync invariant, enforced by a test from commit one.

## Repository layout

```
schemas/      manthana-schemas      (Apache-2.0)  Pydantic models + JSON Schema mirror
collectors/   manthana-collectors   (Apache-2.0)  per-surface transcript adapters
agent/        manthana              (Apache-2.0)  local agent + `manthana` CLI
server/       manthana-server       (AGPL-3.0)    org server (built in a later phase)
tests/        cross-package tests (incl. the personal-mode invariant)
spec/         specification + realized architecture
LICENSES/     full license texts (Apache-2.0, AGPL-3.0, MIT-ECC)
```

All four packages share the PEP 420 namespace `manthana` (`manthana.schemas`,
`manthana.collectors`, `manthana.agent`, `manthana.server`) but are separately
distributable so the AGPL/Apache split is real.

## Development

Requires [`uv`](https://docs.astral.sh/uv/). Python is pinned to 3.12 via
`.python-version` (packages support 3.11+).

```bash
uv sync --all-packages          # create .venv and install all members editable
uv run ruff check .             # lint
uv run pyright                  # type-check
uv run pytest                   # tests (incl. personal-mode invariant)
uv run manthana-schemas-export  # regenerate schemas/json/*.schema.json
uv run manthana datahome        # show resolved MANTHANA_DATA_HOME + db path
```

## For the engineer (your own machine)

After capture (`manthana watch` / the dashboard's Capture button), your work is
queryable and you can run Claude Code more efficiently:

```bash
manthana insights --since 7d           # token-free: projects, outcomes, est. cost
manthana ask "what did I work on last week?"   # grounded, cited (uses your model)
manthana ask "..." --source full       # exclude the cheap Claude-summary digests
manthana optimize status               # headroom (context compression) status
manthana optimize setup                # wire Claude Code through headroom
manthana optimize tune                 # mine your history into CLAUDE.md
```

Manthana **reuses Claude Code's own compaction summaries**: heavy sessions Claude
already summarized compact cheaply (it feeds that summary, not the full transcript),
`manthana watch` auto-compacts those summarized sessions by default, and Ask
defaults to the cheapest digest (toggle to full-only).

The same lives in the dashboard (`uv run manthana dashboard`): the **Ask** page
(insights + grounded Q&A) and the **Optimize** page (headroom setup + savings).
Optimize needs the extra: `uv sync --extra optimize` (or `pip install
"headroom-ai[proxy,mcp]"`); it degrades to an install hint when absent.

## Deploying for a team

Full team setup is two short guides:
- **[docs/deploy.md](docs/deploy.md)** — admin: `docker compose up` runs the
  server + Postgres + MinIO; provision engineers with `manthana-server onboard`.
- **[docs/onboarding.md](docs/onboarding.md)** — employee: one-time `manthana
  login` + `manthana service install`, then it runs itself (capture + auto-sync);
  daily use is the dashboard only.

## Running the server (single host / dev)

Configuration comes from `MANTHANA_SERVER_*` environment variables. **Keep
secrets in a `.env` file — never on the command line** (they leak into shell
history, process lists, and logs). `.env` is gitignored; `.env.example` is the
committed template.

```bash
cp .env.example .env            # then edit .env: set JWT secret, admin token, etc.
docker compose up -d            # full stack (server + Postgres + MinIO), or:
./scripts/serve.sh --port 8000  # just the server, loading .env, against your own DB
```

`scripts/serve.sh` just sources `.env` and runs the server; the equivalent by
hand is:

```bash
set -a; source .env; set +a     # export everything assigned in .env
uv run manthana-server serve --port 8000
```

Then open the **founder console** at <http://127.0.0.1:8000/ui> (sign in with
`MANTHANA_SERVER_ADMIN_TOKEN`) and the local **employee dashboard** with
`uv run manthana dashboard` (<http://127.0.0.1:8765>).

**Real founder narratives.** By default the narrative provider is a deterministic
mock (returns "insufficient data"). For real, citation-grounded narratives,
install the extra and set the provider + key in `.env`:

```bash
uv pip install "anthropic"      # or sync the manthana-server[llm] extra
# in .env:
#   MANTHANA_SERVER_LLM=anthropic
#   ANTHROPIC_API_KEY=sk-ant-...
```

Postgres + MinIO for a full local stack come from `docker compose up -d`
(Postgres is published on host port **5433**; install the driver with
`uv pip install "psycopg[binary]"`). If a key ever lands on a command line or in
a shared transcript, **rotate it** at console.anthropic.com.

## Licensing

Dual-licensed by component — see [`LICENSE`](LICENSE). The server is
AGPL-3.0-or-later; all client tooling is Apache-2.0. Portions are derived from
[ECC](https://github.com/affaan-m/ecc) (MIT, © 2026 Affaan Mustafa); see
[`NOTICE`](NOTICE).
