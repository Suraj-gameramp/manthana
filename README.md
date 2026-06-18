# Manthana

Open-source, local-first platform that captures every AI coding interaction
across an organization, distills each session into a typed **compaction**, and
gives founders grounded, citation-backed visibility — while the employee owns
the local store and the org sees only what is explicitly released.

See the full specification under [`spec/`](spec/) and the realized,
code-grounded architecture in
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

## Licensing

Dual-licensed by component — see [`LICENSE`](LICENSE). The server is
AGPL-3.0-or-later; all client tooling is Apache-2.0. Portions are derived from
[ECC](https://github.com/affaan-m/ecc) (MIT, © 2026 Affaan Mustafa); see
[`NOTICE`](NOTICE).
