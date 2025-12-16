# syntax=docker/dockerfile:1.7

FROM node:22-bookworm AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ARG PNPM_VERSION=10.18.3
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

FROM base AS pruner
WORKDIR /app
ARG APP_NAME
RUN --mount=type=bind,source=.,target=/src,ro \
    pnpm dlx turbo prune @unique-ag/${APP_NAME} --docker --cwd /src --out-dir /app/out

FROM base AS deps
WORKDIR /app

COPY --from=pruner /app/out/json/ .
RUN --mount=type=bind,source=.,target=/src,ro \
    cp /src/pnpm-lock.yaml /app/ && \
    cp /src/pnpm-workspace.yaml /app/

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

FROM base AS builder
ARG APP_NAME
WORKDIR /app

COPY --from=deps /app/ .
RUN --mount=type=bind,source=.,target=/src,ro \
    cp /src/tsconfig.json /app/ && \
    cp /src/turbo.json /app/
COPY --from=pruner /app/out/full/ .
RUN --mount=type=bind,source=.,target=/src,ro \
    test -d /src/services/${APP_NAME}/prisma && \
    cp -r /src/services/${APP_NAME}/prisma /app/services/${APP_NAME}/prisma || true

RUN pnpm --filter=@unique-ag/${APP_NAME} db:generate && \
    # This triggers Prisma to download the engines, so we can stash them in the image.
    pnpm --filter=@unique-ag/${APP_NAME} exec prisma --version && \
    pnpm --filter=@unique-ag/${APP_NAME} codegen
RUN --mount=type=cache,target=/root/.cache/turbo \
    pnpm turbo build --filter=@unique-ag/${APP_NAME}... && \
    pnpm --filter=@unique-ag/${APP_NAME} deploy out

RUN set -eux; \
    cd services/${APP_NAME}; \
    ENG_DIR="$(node -e "console.log(require.resolve('@prisma/engines/package.json'))" | xargs dirname)"; \
    echo "Engines resolved to: $ENG_DIR"; \
    test -d "$ENG_DIR"; \
    mkdir -p /app/_engines; \
    cp -R "$ENG_DIR"/. /app/_engines;

FROM node:22-bookworm-slim AS runner
ARG APP_NAME
ARG PNPM_VERSION=10.18.3
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
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/@generated ./@generated
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/public ./public
COPY --from=builder --chown=nestjs:nodejs /app/services/${APP_NAME}/prisma ./prisma
COPY --from=builder --chown=nestjs:nodejs /app/out/node_modules ./node_modules
COPY --from=builder --chown=nestjs:nodejs /app/out/package.json ./package.json
COPY --from=builder --chown=nestjs:nodejs /app/_engines /prisma/engines

# Create symlink to the correct schema engine binary for the current platform
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

USER nestjs
EXPOSE 3000

ENTRYPOINT ["dumb-init", "--"]
CMD ["sh", "-c", "node --enable-source-maps --max-old-space-size=${MAX_HEAP_MB:-1024} dist/main.js"]
