# syntax=docker/dockerfile:1.7

ARG APP_NAME=demo-ir-mcp

FROM node:26.4.0-trixie@sha256:b46a10d964ad15136ebdf9012142131481caa0697d7a4d4eafe4bbabd818f876 AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN npm install -g pnpm@10.28.1

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
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
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

FROM node:26.4.0-trixie-slim@sha256:a1d9d671994fc2d26e297ac56b4b1522a8bc7fa71c43b14cd1b1fe6c5116f7dc AS runner
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    dumb-init \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs --shell /bin/bash --create-home nestjs

ENV NODE_ENV=production
ENV PORT=9542

COPY --from=builder --chown=nestjs:nodejs /app/services/demo-ir-mcp/dist ./dist
COPY --from=builder --chown=nestjs:nodejs /app/out/node_modules ./node_modules
COPY --from=builder --chown=nestjs:nodejs /app/out/package.json ./package.json

USER nestjs
EXPOSE 9542

ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "--enable-source-maps", "dist/main.js"]
