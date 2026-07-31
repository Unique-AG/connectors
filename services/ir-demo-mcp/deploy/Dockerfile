# syntax=docker/dockerfile:1.7

ARG APP_NAME=ir-demo-mcp

FROM node:26.5.0-trixie@sha256:0473e7dc433a1310f436edee02aa79737ec78a4b345433ab0963d4a256f9ad85 AS base
ENV CI=1 \
    PNPM_STORE_DIR=/root/.local/share/pnpm/store
# Keep the version in sync with "packageManager" in the root and service package.json.
RUN npm install -g pnpm@10.34.5 \
 && pnpm config set store-dir "$PNPM_STORE_DIR"

FROM base AS pruner
ARG APP_NAME
WORKDIR /app
RUN --mount=type=bind,source=.,target=/src,ro \
    pnpm dlx turbo prune @unique-ag/${APP_NAME} --docker --cwd /src --out-dir /app/out

FROM base AS deps
WORKDIR /app
COPY --from=pruner /app/out/json/ .
COPY ./pnpm-lock.yaml ./pnpm-lock.yaml
COPY ./pnpm-workspace.yaml ./pnpm-workspace.yaml
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

FROM base AS builder
ARG APP_NAME
WORKDIR /app
COPY --from=deps /app/ .
COPY ./tsconfig.json ./tsconfig.json
COPY ./turbo.json ./turbo.json
COPY --from=pruner /app/out/full/ .
RUN --mount=type=cache,target=/root/.cache/turbo \
    pnpm turbo build --filter=@unique-ag/${APP_NAME}... && \
    pnpm --filter=@unique-ag/${APP_NAME} deploy out

FROM node:26.5.0-trixie-slim@sha256:715e55e4b84e4bb0ff48e49b398a848f08e55daed8eb6a0ea1839ae53bc57583 AS runner
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
ENV PORT=9542

COPY --from=builder --chown=node:node /app/services/ir-demo-mcp/dist ./dist
COPY --from=builder --chown=node:node /app/out/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/out/package.json ./package.json

USER node
EXPOSE 9542

ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "--enable-source-maps", "dist/main.js"]
