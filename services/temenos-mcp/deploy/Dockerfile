# syntax=docker/dockerfile:1.7

ARG APP_NAME=temenos-mcp

# ------------------------------------------------------------------------------
# Stage 1: base
# Shared foundation for pruner, deps, and builder stages.
# Using full trixie image (not slim) because we need build tools for native modules.
# ------------------------------------------------------------------------------
FROM node:26.3.0-trixie@sha256:f9a1756160a9e1c3dca456bc0b185bf8f2f112a6771c694df87288046f4306f1 AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
# Install pnpm directly. Node 25+ no longer bundles corepack.
# Keep the version in sync with "packageManager" in the root package.json.
RUN npm install -g pnpm@10.28.1

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
FROM node:26.3.0-trixie-slim@sha256:95a34da32a840bd9b3b09a5b773591c16923e350174b1c50e1200c75bf15eaa9 AS runner
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

ENV NODE_ENV=production

COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/dist ./dist
COPY --from=builder --chown=nestjs:nodejs /app/out/node_modules ./node_modules
COPY --from=builder --chown=nestjs:nodejs /app/out/package.json ./package.json

# Run as non-root for security
USER nestjs
EXPOSE 9543

ENTRYPOINT ["dumb-init", "--"]
CMD ["sh", "-c", "node --enable-source-maps --max-old-space-size=${MAX_HEAP_MB:-850} dist/main.js"]
