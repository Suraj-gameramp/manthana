# Manthana org server image.
# Build from the REPO ROOT (the server's deps are workspace path-packages):
#   docker build -f server/Dockerfile -t manthana-server .
# Or via docker-compose (build.context = repo root).
#
# SPDX-License-Identifier: AGPL-3.0-or-later
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

# Install all workspace members from the committed lockfile, plus the server's
# production extras (Postgres driver, S3, real LLM provider).
RUN uv sync --all-packages --frozen \
 && uv pip install "psycopg[binary]>=3.2" "boto3>=1.35" "anthropic>=0.40"

ENV PATH="/app/.venv/bin:$PATH"

# Run as a non-root user (the server needs no write access to the image).
RUN useradd --create-home --uid 10001 manthana && chown -R manthana:manthana /app
USER manthana

EXPOSE 8000
# build_default_app() wires config from MANTHANA_SERVER_* env vars and creates
# tables on startup (idempotent).
CMD ["uvicorn", "manthana.server.app:build_default_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
