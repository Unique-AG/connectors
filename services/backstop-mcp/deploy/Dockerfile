# syntax=docker/dockerfile:1.7

# Builder: Astral's image with uv + Python 3.12 already installed
FROM ghcr.io/astral-sh/uv:0.12.5-python3.12-trixie-slim@sha256:4677e08839853fe91c523b593f822ec1e87c7b91ba4c6b30929016b2e0933cd5 AS builder
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
FROM python:3.14-slim-trixie@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5 AS runtime
WORKDIR /app
RUN groupadd --system --gid 1000 app && useradd --system --uid 1000 --gid app app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8000
USER app
EXPOSE 8000
CMD ["backstop-mcp"]
