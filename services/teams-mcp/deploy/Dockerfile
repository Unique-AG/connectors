# syntax=docker/dockerfile:1.7

FROM node:24-bookworm AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ARG PNPM_VERSION=10.22.0
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

FROM base AS pruner
WORKDIR /app
ARG APP_NAME
RUN --mount=type=bind,source=.,target=/src,ro \
    pnpm dlx turbo prune @unique-ag/${APP_NAME} --docker --cwd /src --out-dir /app/out

FROM base AS deps
WORKDIR /app

COPY --from=pruner /app/out/json/ .
COPY ./pnpm-lock.yaml ./pnpm-lock.yaml
COPY ./pnpm-workspace.yaml ./pnpm-workspace.yaml

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

FROM base AS builder
ARG APP_NAME
WORKDIR /app

COPY --from=deps /app/ .
COPY ./tsconfig.json ./tsconfig.json
COPY ./turbo.json ./turbo.json
COPY --from=pruner /app/out/full/ .

RUN pnpm --filter=@unique-ag/${APP_NAME} codegen
RUN --mount=type=cache,target=/root/.cache/turbo \
    pnpm turbo build --filter=@unique-ag/${APP_NAME}... && \
    pnpm --filter=@unique-ag/${APP_NAME} deploy out

FROM node:24-bookworm-slim AS runner
ARG APP_NAME
ARG PNPM_VERSION=10.22.0
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    openssl \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs --shell /bin/bash --create-home nestjs

ENV PNPM_HOME="/tmp/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV COREPACK_HOME="/tmp/.cache/corepack"
RUN corepack enable
RUN corepack prepare pnpm@${PNPM_VERSION} --activate
RUN mkdir -p /tmp/.cache/corepack && chown -R nestjs:nodejs /tmp/.cache/corepack

ENV NODE_ENV=production

COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/dist ./dist
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/public ./public
COPY --from=builder --chown=nestjs:nodejs /app/out/node_modules ./node_modules
COPY --from=builder --chown=nestjs:nodejs /app/out/package.json ./package.json
# Copy Drizzle migrations and config file for drizzle-kit
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/drizzle ./drizzle
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/drizzle.config.ts ./drizzle.config.ts

USER nestjs
EXPOSE 3000

ENTRYPOINT ["dumb-init", "--"]
CMD ["sh", "-c", "node --enable-source-maps --max-old-space-size=${MAX_HEAP_MB:-1024} dist/main.js"]
