# syntax=docker/dockerfile:1.7

ARG APP_NAME=sharepoint-connector

# ------------------------------------------------------------------------------
# Stage 1: base
# Shared foundation for pruner, deps, and builder stages.
# Using full bookworm image (not slim) because we need build tools for native modules.
# ------------------------------------------------------------------------------
FROM node:24-bookworm AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
# Corepack manages pnpm version from package.json "packageManager" field
RUN corepack enable

# ------------------------------------------------------------------------------
# Stage 2: pruner
# Extracts only the files needed for this service from the monorepo.
# Outputs to /app/out/json (package.jsons) and /app/out/full (source code).
# ------------------------------------------------------------------------------
FROM base AS pruner
ARG APP_NAME
WORKDIR /app
# Bind mount is faster than COPY and doesn't add to image layers
RUN --mount=type=bind,source=.,target=/src,ro \
    pnpm dlx turbo prune @unique-ag/${APP_NAME} --docker --cwd /src --out-dir /app/out

# ------------------------------------------------------------------------------
# Stage 3: deps
# Installs dependencies in a cached layer.
# Only package.json files are copied first for better layer caching.
# ------------------------------------------------------------------------------
FROM base AS deps
WORKDIR /app

COPY --from=pruner /app/out/json/ .
COPY ./pnpm-lock.yaml ./pnpm-lock.yaml
COPY ./pnpm-workspace.yaml ./pnpm-workspace.yaml

# Cache mount persists pnpm store between builds for faster installs
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ------------------------------------------------------------------------------
# Stage 4: builder
# Compiles TypeScript and creates a standalone deployment.
# ------------------------------------------------------------------------------
FROM base AS builder
ARG APP_NAME
WORKDIR /app

COPY --from=deps /app/ .
COPY ./tsconfig.json ./tsconfig.json
COPY ./turbo.json ./turbo.json
COPY --from=pruner /app/out/full/ .

# Build this package and all workspace dependencies (...), then create standalone deployment
RUN --mount=type=cache,target=/root/.cache/turbo \
    pnpm turbo build --filter=@unique-ag/${APP_NAME}... && \
    pnpm --filter=@unique-ag/${APP_NAME} deploy out

# ------------------------------------------------------------------------------
# Stage 5: runner
# Minimal production image. Only this stage is included in the final image.
# ------------------------------------------------------------------------------
FROM node:24-bookworm-slim AS runner
ARG APP_NAME
WORKDIR /app

# dumb-init: proper PID 1 that forwards signals (for graceful shutdown)
# openssl: required for TLS connections
# ca-certificates: trust store for HTTPS
# curl: health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    openssl \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs --shell /bin/bash --create-home nestjs

# pnpm/corepack kept for consistency with other services, though this service
# has no database migrations. Can be removed if image size is a concern.
ENV PNPM_HOME="/tmp/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV COREPACK_HOME="/tmp/.cache/corepack"
RUN corepack enable
RUN mkdir -p $COREPACK_HOME && chown -R nestjs:nodejs $COREPACK_HOME

ENV NODE_ENV=production

COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/dist ./dist
COPY --from=builder --chown=nestjs:nodejs /app/out/node_modules ./node_modules
COPY --from=builder --chown=nestjs:nodejs /app/out/package.json ./package.json

# Run as non-root for security
USER nestjs
EXPOSE 3000

ENTRYPOINT ["dumb-init", "--"]
CMD ["sh", "-c", "node --enable-source-maps --max-old-space-size=${MAX_HEAP_MB:-1024} dist/main.js"]
