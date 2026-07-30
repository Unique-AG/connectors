# syntax=docker/dockerfile:1.7

# Builder: Astral's image with uv + Python 3.12 already installed
FROM ghcr.io/astral-sh/uv:0.11.33-python3.12-trixie-slim@sha256:7b5a3c8f80fb965911cf8f0c6690b30b39f10f691fc1e52cd6cc44bc509c3aeb AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=services/backstop-mcp/uv.lock,target=uv.lock \
    --mount=type=bind,source=services/backstop-mcp/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable
COPY services/backstop-mcp /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Runtime: no uv binary — only venv + system Python 3.12
FROM python:3.12-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime
WORKDIR /app
RUN groupadd --system --gid 1001 app && useradd --system --uid 1001 --gid app app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8000
USER app
EXPOSE 8000
CMD ["backstop-mcp"]
