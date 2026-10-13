# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.12-slim-bookworm AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# uv sync --frozen needs every workspace member's manifest; the glob picks up new members automatically.
COPY --parents services/*/pyproject.toml services/*/*/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package tiingo-mcp
COPY services/tiingo-mcp/src services/tiingo-mcp/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package tiingo-mcp

FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 10001 app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=9542 PYTHON_ENV=production MCP_AUTH_MODE=zitadel
USER app
WORKDIR /app
EXPOSE 9542
CMD ["tiingo-mcp"]
