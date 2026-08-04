# syntax=docker/dockerfile:1.7

ARG APP_NAME=outlook-semantic-mcp

# ------------------------------------------------------------------------------
# Stage 1: base
# Shared foundation for pruner, deps, and builder stages.
# Using full trixie image (not slim) because we need build tools for native modules.
# ------------------------------------------------------------------------------
FROM node:26.5.0-trixie@sha256:0473e7dc433a1310f436edee02aa79737ec78a4b345433ab0963d4a256f9ad85 AS base
ENV CI=1 \
    PNPM_STORE_DIR=/root/.local/share/pnpm/store
# Keep the version in sync with "packageManager" in the root and service package.json.
RUN npm install -g pnpm@10.34.5 \
 && pnpm config set store-dir "$PNPM_STORE_DIR"

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
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
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

# Generate GraphQL types from schema
RUN pnpm --filter=@unique-ag/${APP_NAME} codegen
# Build this package and all workspace dependencies (...), then create standalone deployment
RUN --mount=type=cache,target=/root/.cache/turbo \
    pnpm turbo build --filter=@unique-ag/${APP_NAME}... && \
    pnpm --filter=@unique-ag/${APP_NAME} deploy out

# ------------------------------------------------------------------------------
# Stage 5: runner
# Minimal production image. Only this stage is included in the final image.
# ------------------------------------------------------------------------------
FROM node:26.5.0-trixie-slim@sha256:715e55e4b84e4bb0ff48e49b398a848f08e55daed8eb6a0ea1839ae53bc57583 AS runner
ARG APP_NAME
WORKDIR /app

# Baseline runtime packages:
#   - procps/dumb-init/openssl/ca-certificates: signal forwarding, TLS, trust store
#   - apt-get upgrade: pull newest OS security patches at build time
# pnpm is kept in every runtime for homogeneity. npm and npx are removed afterwards
# to shrink the runtime attack surface.
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends \
      procps \
      dumb-init \
      openssl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g pnpm@10.34.5 \
 && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

ENV NODE_ENV=production

COPY --from=builder --chown=node:node /app/services/${APP_NAME}/dist ./dist
COPY --from=builder --chown=node:node /app/services/${APP_NAME}/public ./public
COPY --from=builder --chown=node:node /app/out/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/out/package.json ./package.json
# Drizzle ORM migration files
COPY --from=builder --chown=node:node /app/services/${APP_NAME}/drizzle ./drizzle
COPY --from=builder --chown=node:node /app/services/${APP_NAME}/drizzle.config.ts ./drizzle.config.ts

# Run as non-root for security
USER node
EXPOSE 3000

ENTRYPOINT ["dumb-init", "--"]
CMD ["sh", "-c", "node --enable-source-maps --max-old-space-size=${MAX_HEAP_MB:-850} dist/main.js"]
