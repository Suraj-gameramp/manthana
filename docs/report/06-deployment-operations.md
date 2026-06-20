# Deployment and Operations

Deploy Manthana as a full-stack team solution (org server + employee agents), or run the local agent standalone — everything is open-source and self-hosted.

---

## Table of contents

1. [Architecture overview](#architecture-overview)
2. [Admin: deploy the org server](#admin-deploy-the-org-server)
3. [Admin: provision engineers](#admin-provision-engineers)
4. [Employee: one-time setup](#employee-one-time-setup)
5. [Configuration and secrets](#configuration-and-secrets)
6. [The hands-off daemon](#the-hands-off-daemon)
7. [Scaling beyond Docker Compose](#scaling-beyond-docker-compose)
8. [Operations runbook](#operations-runbook)
9. [Architecture diagram](#architecture-diagram)

---

## Architecture overview

**Two-tier deployment:**

- **Org server** (`manthana-server`, AGPL-3.0): one host with Postgres + MinIO (or cloud S3). Ingests released, redacted compactions from engineers; serves the founder console (`/ui`) + founder query API.
- **Employee agents** (Apache-2.0): one per laptop. Captures transcripts locally (no cloud), auto-compacts on demand, and syncs released compactions to the org server.

**Data flow:**
- Engineer writes code in Claude Code → local `~/.claude/projects/*.jsonl` transcripts.
- `manthana watch` daemon ingests transcripts, auto-compacts summarized sessions, stores in local SQLite.
- Engineer reviews compactions in the dashboard, toggles Work/Personal, and clicks Release.
- Released, redacted compactions auto-sync to the org server.
- Founder logs into `/ui` console, runs queries (NL → k-anon-gated, grounded narrative), mines org-wide skills.

**Trust boundary:** Personal-mode sessions never leave the laptop (enforced by `tests/test_personal_mode_invariant.py`). Secrets and PII are redacted on release. All org-visible data is released + redacted + k-anonymized (≥4 distinct contributors per aggregate).

---

## Admin: deploy the org server

The server runs on one host. Postgres and MinIO (or S3) are the only stateful dependencies; the server itself is stateless and can scale to multiple replicas.

### One-command full stack (macOS / Linux with Docker)

```bash
git clone https://github.com/Suraj-gameramp/manthana.git
cd manthana
cp .env.example .env
# Edit .env: set JWT_SECRET, ADMIN_TOKEN (see below for values)
docker compose up -d
# Postgres on :5433, MinIO console on :9001, API on :8000
docker compose ps  # wait for all healthy
```

Health checks:
- `/healthz` — liveness (always 200 if the process is alive)
- `/readyz` — readiness (200 only when DB and object store are reachable)

Founder console: <http://localhost:8000/ui> (sign in with `MANTHANA_SERVER_ADMIN_TOKEN`)
API docs: <http://localhost:8000/docs>

### Production: run the published image

Skip the source build; pull the released image from GHCR:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Pin to a specific version:
MANTHANA_VERSION=0.2.0 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The `docker-compose.prod.yml` overlay replaces the local build with `ghcr.io/suraj-gameramp/manthana-server:<version>` and inherits Postgres/MinIO from the base file.

### Server-only (without Compose — your own Postgres + S3)

```bash
./scripts/serve.sh --port 8000
# Loads .env, exports all vars, runs:
#   uv run manthana-server serve --port 8000
```

Equivalent without the helper:
```bash
set -a; source .env; set +a
uv run manthana-server serve --port 8000
```

Requires:
- `MANTHANA_SERVER_DB_URL` — PostgreSQL or SQLite
- `MANTHANA_SERVER_OBJECT_STORE` — "s3" or "memory" (dev)
- `MANTHANA_SERVER_JWT_SECRET`, `MANTHANA_SERVER_ADMIN_TOKEN` (non-empty in prod)

---

## Configuration and secrets

All secrets live in `.env` (gitignored). **Never put them on the command line** — they leak into shell history, process lists, and logs. If a secret ever appears in a command line or shared transcript, rotate it immediately.

### Secrets (required in production)

| Variable | Purpose | Example |
|---|---|---|
| `MANTHANA_SERVER_JWT_SECRET` | Signs agent tokens (≥32 random bytes; `openssl rand -hex 32`) | `abc123...` |
| `MANTHANA_SERVER_ADMIN_TOKEN` | Gates founder console + admin/founder API (any value, ≥16 bytes recommended) | `my-secret-admin-token` |

The server rejects empty secrets at startup.

### Storage

| Variable | Purpose | Default | Example |
|---|---|---|---|
| `MANTHANA_SERVER_DB_URL` | Postgres (prod) or SQLite (dev) | `sqlite:///./manthana-server.db` | `postgresql+psycopg://user:pass@host:5432/manthana` |
| `MANTHANA_SERVER_OBJECT_STORE` | Where to store raw transcripts | `memory` | `s3` |
| `MANTHANA_SERVER_S3_BUCKET` | S3/MinIO bucket name | — | `manthana-raw` |
| `MANTHANA_SERVER_S3_ENDPOINT_URL` | S3-compatible endpoint (omit for AWS S3) | — | `http://localhost:9000` |
| `MANTHANA_SERVER_S3_ACCESS_KEY` | S3 access key (else boto3 default cred chain) | — | `manthana` |
| `MANTHANA_SERVER_S3_SECRET_KEY` | S3 secret key | — | `manthana-secret` |

**Docker Compose note:** the base `docker-compose.yml` overrides `MANTHANA_SERVER_DB_URL` and S3 settings for the in-cluster server, so you only need to set them when running `./scripts/serve.sh` against an external database.

### Privacy and LLM provider

| Variable | Purpose | Default | Example |
|---|---|---|---|
| `MANTHANA_SERVER_K_ANON` | k-anonymity floor for founder aggregates | `4` | `1` (dev only) |
| `MANTHANA_SERVER_LLM` | Founder-narrative provider | `mock` | `anthropic` |
| `MANTHANA_SERVER_LLM_MODEL` | Model for narratives | `claude-sonnet-4-6` | `claude-opus-4-8` |
| `MANTHANA_SERVER_LLM_MAX_TOKENS` | Narrative output ceiling | `1024` | `2048` |
| `ANTHROPIC_API_KEY` | Anthropic API key (required when `LLM=anthropic`) | — | `sk-ant-...` |

**Default behavior:** narratives return "insufficient data" (mock provider, no token spend). For real, citation-grounded narratives, set `MANTHANA_SERVER_LLM=anthropic` and provide the API key.

### Example `.env`

```bash
# ── Secrets ──
MANTHANA_SERVER_JWT_SECRET="$(openssl rand -hex 32)"
MANTHANA_SERVER_ADMIN_TOKEN="$(openssl rand -hex 24)"

# ── Storage (docker-compose overrides these for in-cluster server) ──
MANTHANA_SERVER_DB_URL="postgresql+psycopg://manthana:manthana@localhost:5433/manthana"
MANTHANA_SERVER_OBJECT_STORE="memory"

# ── Privacy ──
MANTHANA_SERVER_K_ANON="4"

# ── LLM (optional) ──
MANTHANA_SERVER_LLM="mock"
# ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Admin: provision engineers

One command per engineer; creates the org + team (idempotent) and mints a token valid for 365 days.

```bash
docker compose exec server manthana-server onboard \
    acme "Acme Inc"  platform "Platform"  alice@acme.com
```

Output:
```
provisioned org=acme team=platform actor=alice@acme.com
eyJhbGc... (engineer's 365-day JWT)
```

Share the printed token with the employee for their one-time `manthana login`.

**Team composition:** Cross-engineer features (like skill mining) require ≥4 distinct contributors to meet the k-anonymity floor. Onboard the team, not just one person.

---

## Employee: one-time setup

Each engineer runs this once on their laptop.

### 1. Connect to the org server

```bash
manthana login \
    --server https://manthana.yourco.com \
    --token <TOKEN_FROM_ADMIN> \
    --actor alice@acme.com
```

This writes `~/.manthana/manthana.toml` and verifies the connection.

### 2. Verify the setup

```bash
manthana config          # shows the stored URL + actor
manthana sync --check    # confirms the server is reachable
```

### 3. Install the daemon (macOS)

```bash
manthana service install
# logs: ~/Library/Logs/manthana-watch.log
```

The daemon now starts at login and runs `manthana watch`, which:
- Ingests new/changed Claude Code transcripts (every 5 seconds, no token cost)
- Auto-syncs released, redacted, non-personal compactions to the org server

### Linux equivalent

Create a systemd user unit:
```bash
systemctl --user enable --now manthana-watch
# Create ~/.config/systemd/user/manthana-watch.service running: manthana watch
```

---

## The hands-off daemon

`manthana watch` is the core of the employee experience: it runs continuously, captures new work, and syncs to the org with zero manual intervention (except release decisions).

### Behavior

**Polling (default every 5 seconds):**
1. Globs `~/.claude/projects/*/*.jsonl` (Claude Code transcripts)
2. Compares mtimes against the last-seen state (incremental, no re-ingest of unchanged files)
3. On new/changed files: calls `ingest_file`, which flattens turns and stores sessions in the local SQLite
4. **Auto-compacts summarized sessions** (default on, `--no-compact-summarized` to disable) — Claude Code often includes session summaries in the transcript; Manthana feeds those summaries to the compactor (cheap, ~1M tokens → ~15K chars) instead of the full transcript
5. **Optional full auto-compact** (`--compact` flag) — costs tokens; off by default
6. **Auto-syncs released compactions** (default on, `--no-sync` to disable) — every synced compaction is redacted on the way out

### CLI

```bash
manthana watch              # default: 5s interval, auto-compact summarized, auto-sync
manthana watch --interval 10
manthana watch --compact    # full auto-compact (costs tokens)
manthana watch --no-sync    # capture + compact only
```

### Error handling

- File read errors (partial writes, perms) are logged and retried next cycle (eventual consistency)
- Ingestion errors (malformed JSONL) are logged per-file and don't block other files
- Sync failures are logged; the compaction is marked for retry on the next cycle
- Ctrl-C stops cleanly and closes the database

### Launchd service (macOS)

The daemon plist is written to `~/Library/LaunchAgents/com.manthana.watch.plist` by `manthana service install`:

```bash
manthana service status              # check if installed and running
manthana service uninstall           # remove the plist
launchctl list | grep manthana       # manual check
log stream --level debug --predicate 'process == "manthana"'  # tail logs
```

---

## Daily employee workflow

Everything happens in the **dashboard**:

```bash
manthana dashboard
# Opens http://127.0.0.1:8765
```

### Sessions page
- Review captured sessions (Work / Personal toggle)
- Click **Compact** to summarize (costs tokens from your Claude account)
- **Compactions** page shows the summary; click **Release** to share

### Compactions page
- Review-before-sync inbox
- Each released compaction auto-syncs to the org on the next `watch` cycle
- **Cost** page shows token spend + USD estimate

### Skills page
- View locally-mined skills (from your own compactions)
- **Ask** to query your own history (grounded, cited, uses your model)

---

## Network and TLS

Docker Compose binds the server on `:8000` (HTTP only, localhost). For a team:

1. **Reverse proxy** (Caddy, nginx, or a cloud load balancer) in front, terminating TLS
2. Point engineers at `https://manthana.yourco.com`
3. The proxy forwards to `server:8000` (internal, HTTP)

```nginx
# Example nginx upstream
upstream manthana {
  server server:8000;
}
server {
  listen 443 ssl;
  server_name manthana.yourco.com;
  # ... ssl_certificate, ssl_key ...
  location / {
    proxy_pass http://manthana;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
  }
}
```

---

## Scaling beyond Docker Compose

### Kubernetes

Published image: `ghcr.io/suraj-gameramp/manthana-server:<version>` (e.g. `:0.2.0`)

**Prerequisites:**
- External Postgres (managed service, e.g. AWS RDS + pgvector extension)
- External S3/MinIO (AWS S3, GCS, DigitalOcean Spaces, or self-hosted MinIO)

**Deploy:**

```bash
# Create ConfigMap (non-secret config)
kubectl apply -f deploy/k8s/configmap.yaml

# Create Secret (JWT secret, admin token, API key)
kubectl create secret generic manthana-server-secrets \
  --from-literal=MANTHANA_SERVER_JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=MANTHANA_SERVER_ADMIN_TOKEN="$(openssl rand -hex 24)" \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..."  # if using real LLM

# Deploy
kubectl apply -f deploy/k8s/deployment.yaml -f deploy/k8s/service.yaml

# Verify
kubectl get pods
kubectl logs deployment/manthana-server
```

**Pod spec:**
- **Image:** `ghcr.io/suraj-gameramp/manthana-server:0.2.0` (pinned)
- **Uid:** 10001 (non-root, capabilities dropped)
- **Ports:** 8000/TCP
- **Probes:**
  - Liveness: `GET /healthz` (every 15s, fail after 12 retries = ~3min)
  - Readiness: `GET /readyz` (every 10s, DB-ping gated)
- **Resources:** requests `100m CPU / 256Mi RAM`, limits `512Mi RAM`
- **Replicas:** 1 by default (can scale to N once Postgres/S3 are external)

**Ingress:** Put a cloud ingress or load balancer in front (AWS ALB, GCP Cloud Load Balancer, etc.) terminating TLS and routing to the Service on port 80.

**Manifest files** in `deploy/k8s/`:
- `configmap.yaml` — non-secret config (DB URL, object store settings, k-anon floor, LLM provider)
- `deployment.yaml` — the server pod, health probes, security context
- `service.yaml` — ClusterIP service on port 80 → 8000
- `secret.example.yaml` — example for creating the Secret (do NOT commit real secrets; use `kubectl create secret` instead)

---

## Operations runbook

### Startup

```bash
# Source .env and run
./scripts/serve.sh --port 8000

# Or with Docker Compose
docker compose up -d && docker compose ps
```

Server is ready when `/readyz` returns 200 (DB connected, object store reachable).

### Check server health

```bash
# Liveness (process alive)
curl http://localhost:8000/healthz
# 200 OK

# Readiness (DB + storage reachable)
curl http://localhost:8000/readyz
# 200 OK

# API docs
open http://localhost:8000/docs
```

### Rotate secrets

**JWT Secret (agent-side):**
1. Generate a new secret: `openssl rand -hex 32`
2. Update `MANTHANA_SERVER_JWT_SECRET` in `.env`
3. Restart the server: `docker compose restart server` (or `kill` the process)
4. **Note:** existing agent tokens (issued under the old secret) become invalid. Re-run `manthana-server onboard` for each engineer to issue new tokens.

**Admin Token:**
1. Generate: `openssl rand -hex 24`
2. Update `MANTHANA_SERVER_ADMIN_TOKEN` in `.env`
3. Restart the server
4. Founder must re-authenticate at `/ui` (cookie expires on logout)

**Anthropic API key:**
1. Rotate at console.anthropic.com
2. Update `ANTHROPIC_API_KEY` in `.env`
3. Restart the server

**Best practice:** Use a secrets manager (HashiCorp Vault, AWS Secrets Manager, etc.) and sync into the container at runtime.

### Backup and restore

**Stateful volumes:**
- `pgdata` — Postgres data (all compactions, orgs, teams, actors)
- `miniodata` — MinIO data (released raw transcripts)

**Docker Compose backup:**
```bash
docker compose exec postgres pg_dump -U manthana manthana > backup.sql
docker run -v miniodata:/data alpine tar czf - /data > minio-backup.tar.gz
```

**Restore:**
```bash
docker compose exec -T postgres psql -U manthana manthana < backup.sql
docker run -v miniodata:/data alpine tar xzf minio-backup.tar.gz -C /
```

**Kubernetes:**
Use your cloud provider's backup service (AWS RDS backups, GCS snapshots) for Postgres. For MinIO, use S3-to-S3 replication or a backup tool like MinIO's own `.mc mirror`.

### Upgrade

**Docker Compose:**
```bash
# Bring the latest source and rebuild
git pull
docker compose up -d --build

# Or pull a specific release
MANTHANA_VERSION=0.3.0 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Kubernetes:**
```bash
# Update the image tag in deployment.yaml or patch it directly
kubectl set image deployment/manthana-server server=ghcr.io/suraj-gameramp/manthana-server:0.3.0
kubectl rollout status deployment/manthana-server
```

### Logs

**Docker Compose:**
```bash
docker compose logs -f server      # server only
docker compose logs -f             # all services
```

**Kubernetes:**
```bash
kubectl logs -f deployment/manthana-server
kubectl logs -f deployment/manthana-server --previous  # if crash-looping
```

**Employee daemon (macOS):**
```bash
tail -f ~/Library/Logs/manthana-watch.log
```

### Monitoring

**Key metrics to track:**
- Agent sync success rate (endpoint: `POST /v1/compactions`, status 201)
- Raw-transcript release success (endpoint: `POST /v1/compactions/{id}/raw`, status 200)
- Founder query latency (endpoint: `POST /v1/founder/query`, depends on LLM provider)
- k-anonymity suppression rate (queries returning "insufficient data")

**Prometheus metrics** (future; not yet published): add custom metrics endpoints at `/metrics` with sync counts, query latencies, and suppression events.

---

## Auditing

### Founder query audit log

Every query (API + `/ui`) is recorded:

```bash
# List all queries for an org
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://localhost:8000/v1/admin/audit?org_id=acme

# Response (future): who asked what, when, whether answered/withheld, citation count
```

The `/ui` console shows a "Recent founder queries" panel.

### Action queue

Skill mining proposals (and future actions) are enqueued in the action queue for approval:

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://localhost:8000/v1/admin/queue
```

Approve proposals via the `/ui` console or directly via the API.

---

## Environment variables reference

### Server-side (`MANTHANA_SERVER_*`)

| Variable | Default | Scope | Notes |
|---|---|---|---|
| `MANTHANA_SERVER_JWT_SECRET` | — | Required | Bearer-token signing secret (≥32 bytes) |
| `MANTHANA_SERVER_ADMIN_TOKEN` | — | Required | Founder console + admin API auth |
| `MANTHANA_SERVER_DB_URL` | `sqlite:///./manthana-server.db` | Storage | Postgres (prod) or SQLite (dev) |
| `MANTHANA_SERVER_OBJECT_STORE` | `memory` | Storage | `memory`, `s3`, or `gcs` |
| `MANTHANA_SERVER_S3_BUCKET` | — | Storage | Required when `OBJECT_STORE=s3` |
| `MANTHANA_SERVER_S3_ENDPOINT_URL` | — | Storage | Optional (MinIO, etc.) |
| `MANTHANA_SERVER_S3_ACCESS_KEY` | — | Storage | Optional (else boto3 default cred chain) |
| `MANTHANA_SERVER_S3_SECRET_KEY` | — | Storage | Optional |
| `MANTHANA_SERVER_K_ANON` | `4` | Privacy | k-anonymity floor (≥1) |
| `MANTHANA_SERVER_LLM` | `mock` | LLM | `mock` or `anthropic` |
| `MANTHANA_SERVER_LLM_MODEL` | `claude-sonnet-4-6` | LLM | Model ID for narratives |
| `MANTHANA_SERVER_LLM_MAX_TOKENS` | `1024` | LLM | Narrative output ceiling (1..100000) |
| `ANTHROPIC_API_KEY` | — | LLM | Required when `LLM=anthropic` |

### Agent-side (`MANTHANA_*`, `MANTHANA_ACTOR`)

| Variable | Default | Scope | Notes |
|---|---|---|---|
| `MANTHANA_DATA_HOME` | `~/.manthana` | Local | SQLite database directory |
| `MANTHANA_ACTOR` | `{git email} \| {OS user}` | Identity | Contributor identity (overrides git/user) |
| `MANTHANA_SERVER_URL` | `[server].url` in toml | Sync | Org server URL |
| `MANTHANA_TEAM_TOKEN` | `[server].token` in toml | Sync | Agent JWT (from `manthana login`) |

---

## Architecture diagram

```mermaid
graph TB
    subgraph "Employee Laptop"
        CCE["Claude Code Editor"]
        TRANSCRIPTS["~/.claude/projects/\n*.jsonl"]
        WATCH["manthana watch\n(daemon)"]
        DASHBOARD["manthana dashboard\nHTMX UI"]
        SQLITE["SQLite\n~/.manthana/\nmanthana.db"]
        REDACTOR["Redactor\n(on-release)"]
    end

    subgraph "Org Server"
        INGRESS["TLS Ingress"]
        APISERVER["FastAPI Server\n/v1/compactions\n/v1/founder/query\n/ui console"]
        POSTGRES["Postgres +\npgvector"]
        MINIO["MinIO / S3\n(raw transcripts)"]
        LLM["LLM Provider\n(Anthropic CLI\nwith API key)"]
    end

    subgraph "Founder Laptop"
        BROWSER["Browser\n(http://server/ui)"]
    end

    CCE -->|writes| TRANSCRIPTS
    TRANSCRIPTS -->|polls| WATCH
    WATCH -->|ingest| SQLITE
    WATCH -->|compact| SQLITE
    SQLITE -->|read| DASHBOARD
    DASHBOARD -->|toggle release| SQLITE
    SQLITE -->|redact| REDACTOR
    REDACTOR -->|sync| INGRESS

    INGRESS -->|POST /v1/compactions| APISERVER
    APISERVER -->|store| POSTGRES
    APISERVER -->|store raw| MINIO
    BROWSER -->|POST /v1/founder/query| APISERVER
    APISERVER -->|NL→filter→SQL| POSTGRES
    APISERVER -->|cite| POSTGRES
    APISERVER -->|narrative| LLM
    BROWSER -->|GET /ui| APISERVER

    classDef local fill:#e8f4f8,stroke:#0288d1,stroke-width:2px
    classDef server fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef external fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px

    class CCE,TRANSCRIPTS,WATCH,DASHBOARD,SQLITE,REDACTOR local
    class INGRESS,APISERVER,POSTGRES,MINIO,LLM server
    class BROWSER,Founder external
```

---

## Troubleshooting

### "Server not reachable" (agent → server)

```bash
# From employee laptop
manthana config        # check the server_url
curl -v https://manthana.yourco.com/healthz  # verify TLS + DNS

# Check the agent's token
manthana sync --check  # detailed error message
```

**Common causes:**
- TLS certificate expired (Ingress/proxy)
- Firewall rule blocking the port
- DNS not resolving `manthana.yourco.com`
- Server restarted or crashed

### "Insufficient data" from founder queries

```bash
# Verify k-anonymity floor
docker compose exec server manthana-server token admin-token \
    --check-org acme

# Count contributors per team
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
    http://localhost:8000/v1/admin/orgs
```

If contributor count < k-anon floor (default 4), queries will suppress results. Onboard more engineers or lower the floor in `.env` (dev only).

### Agent token expired

```bash
# Tokens valid 365 days
docker compose exec server manthana-server onboard \
    acme "Acme Inc" platform "Platform" alice@acme.com
# Share the new token with the engineer
manthana login --token <NEW_TOKEN>
```

### Daemon not capturing new sessions

```bash
# Check if it's running
manthana service status
# or: launchctl list | grep manthana

# Tail the logs
tail -f ~/Library/Logs/manthana-watch.log

# Verify transcripts are being written
ls -la ~/.claude/projects/*/  # should have recent *.jsonl files

# Try capture manually
manthana capture
```

### Compaction returns empty or "insufficient data"

```bash
# Verify the LLM provider is configured
manthana config
uv run manthana compact <session_id>  # manual compact with logging
```

If using the real Anthropic provider, check `ANTHROPIC_API_KEY` is set and has quota. If using mock (dev), narratives always return "insufficient data" (expected).

---

## Next steps

- **[spec/manthana-decisions.md](../spec/manthana-decisions.md)** — locked v1 decisions and architecture
- **[spec/manthana-architecture.md](../spec/manthana-architecture.md)** — code-grounded architecture, schema reference, phase status
- **[docs/deploy.md](./deploy.md)** — concise deploy checklist
- **[docs/onboarding.md](./onboarding.md)** — employee setup walkthrough
