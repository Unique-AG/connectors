# syntax=docker/dockerfile:1.7

ARG APP_NAME=factset-mcp

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
# Compiles TypeScript, generates Prisma client, and creates standalone deployment.
# ------------------------------------------------------------------------------
FROM base AS builder
ARG APP_NAME
WORKDIR /app

COPY --from=deps /app/ .
COPY ./tsconfig.json ./tsconfig.json
COPY ./turbo.json ./turbo.json
COPY --from=pruner /app/out/full/ .
# Prisma schema needed for client generation
COPY ./services/${APP_NAME}/prisma ./services/${APP_NAME}/prisma

# Generate Prisma client, verify it works, then generate GraphQL types
RUN pnpm --filter=@unique-ag/${APP_NAME} db:generate && \
    pnpm --filter=@unique-ag/${APP_NAME} exec prisma --version && \
    pnpm --filter=@unique-ag/${APP_NAME} codegen
# Build this package and all workspace dependencies (...), then create standalone deployment
RUN --mount=type=cache,target=/root/.cache/turbo \
    pnpm turbo build --filter=@unique-ag/${APP_NAME}... && \
    pnpm --filter=@unique-ag/${APP_NAME} deploy out

# Extract Prisma engines to a known location for the runner stage.
# pnpm deploy doesn't include @prisma/engines, so we copy them manually.
RUN set -eux; \
    cd services/${APP_NAME}; \
    ENG_DIR="$(node -e "console.log(require.resolve('@prisma/engines/package.json'))" | xargs dirname)"; \
    echo "Engines resolved to: $ENG_DIR"; \
    test -d "$ENG_DIR"; \
    mkdir -p /app/_engines; \
    cp -R "$ENG_DIR"/. /app/_engines;

# ------------------------------------------------------------------------------
# Stage 5: runner
# Minimal production image. Only this stage is included in the final image.
# ------------------------------------------------------------------------------
FROM node:24-bookworm-slim AS runner
ARG APP_NAME
WORKDIR /app

# dumb-init: proper PID 1 that forwards signals (for graceful shutdown)
# openssl: required for TLS connections and Prisma
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

# pnpm/corepack needed at runtime for migrations via docker-compose command override:
#   command: ["pnpm", "run", "db:migrate"]
# Using /tmp paths because nestjs user can write there
ENV PNPM_HOME="/tmp/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV COREPACK_HOME="/tmp/.cache/corepack"
RUN corepack enable
RUN mkdir -p $COREPACK_HOME && chown -R nestjs:nodejs $COREPACK_HOME

ENV NODE_ENV=production

COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/dist ./dist
# Generated Prisma client
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/@generated ./@generated
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/public ./public
# Prisma schema and migrations
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/prisma ./prisma
COPY --from=builder --chown=nestjs:nodejs /app/out/node_modules ./node_modules
COPY --from=builder --chown=nestjs:nodejs /app/out/package.json ./package.json
# Prisma engines (query engine, schema engine) for migrations
COPY --from=builder --chown=nestjs:nodejs /app/_engines /prisma/engines

# Create symlink for schema engine binary (name varies by platform)
ENV PRISMA_SCHEMA_ENGINE_BINARY=/prisma/engines/schema-engine
RUN set -eux; \
    cd /prisma/engines; \
    SCHEMA_ENGINE=$(find . -name "schema-engine-*" -type f -executable | head -1); \
    if [ -n "$SCHEMA_ENGINE" ]; then \
        ln -sf "$SCHEMA_ENGINE" schema-engine; \
        echo "Created symlink: schema-engine -> $SCHEMA_ENGINE"; \
    else \
        echo "Warning: No schema engine binary found"; \
    fi

# Run as non-root for security
USER nestjs
EXPOSE 3000

ENTRYPOINT ["dumb-init", "--"]
CMD ["sh", "-c", "node --enable-source-maps --max-old-space-size=${MAX_HEAP_MB:-1024} dist/main.js"]
