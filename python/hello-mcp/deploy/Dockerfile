# python/hello-mcp/deploy/Dockerfile
# syntax=docker/dockerfile:1.7

# Builder: Astral's image with uv + Python 3.12 already installed
FROM ghcr.io/astral-sh/uv:0.11.33-python3.12-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=python/hello-mcp/uv.lock,target=uv.lock \
    --mount=type=bind,source=python/hello-mcp/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable
COPY python/hello-mcp /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Runtime: no uv binary — only venv + system Python 3.12
FROM python:3.12-slim-trixie AS runtime
WORKDIR /app
RUN groupadd --system --gid 1001 app && useradd --system --uid 1001 --gid app app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["hello-mcp"]
