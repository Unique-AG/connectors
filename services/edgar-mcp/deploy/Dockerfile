# syntax=docker/dockerfile:1.7

# ------------------------------------------------------------------------------
# Stage 1: builder
# Install dependencies and build the package in an isolated venv.
# Using full bookworm image for build tools needed by native extensions.
# ------------------------------------------------------------------------------
FROM python:3.12-bookworm AS builder

# https://github.com/orgs/astral-sh/packages/container/package/uv
COPY --from=ghcr.io/astral-sh/uv:0.9.22-bookworm-slim@sha256:afe1e539cc1d015f78436cb660a72df1f9ac70af78f629c978a908051995caf5 /uv /bin/uv

# Compile bytecode for faster startup
ENV UV_COMPILE_BYTECODE=1
# Copy from the cache instead of linking since it's a mounted cache
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy dependency files first for layer caching
COPY services/edgar-mcp/pyproject.toml ./pyproject.toml
COPY services/edgar-mcp/uv.lock ./uv.lock

# Install production dependencies without the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy source code and install the project as a regular (non-editable) package
COPY services/edgar-mcp/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ------------------------------------------------------------------------------
# Stage 2: runner
# Minimal production image. Only this stage is included in the final image.
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

# dumb-init: proper PID 1 that forwards signals (for graceful shutdown)
# ca-certificates: trust store for HTTPS
# curl: health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --shell /bin/bash --create-home app

# Copy the venv with all installed packages from builder
COPY --from=builder --chown=app:app /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root for security
USER app
EXPOSE 9542

ENTRYPOINT ["dumb-init", "--"]
CMD ["python", "-m", "edgar_mcp.main"]
