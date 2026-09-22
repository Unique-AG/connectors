# syntax=docker/dockerfile:1.7
ARG APP_NAME=a2a-gateway

FROM node:26.9.0-trixie AS base
ENV CI=1 PNPM_STORE_DIR=/root/.local/share/pnpm/store
RUN npm install -g pnpm@10.34.5 && pnpm config set store-dir "$PNPM_STORE_DIR"

FROM base AS pruner
ARG APP_NAME
WORKDIR /app
RUN --mount=type=bind,source=.,target=/src,ro pnpm dlx turbo prune @unique-ag/${APP_NAME} --docker --cwd /src --out-dir /app/out

FROM base AS deps
WORKDIR /app
COPY --from=pruner /app/out/json/ .
COPY pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile

FROM base AS builder
ARG APP_NAME
WORKDIR /app
COPY --from=deps /app/ .
COPY tsconfig.json turbo.json ./
COPY --from=pruner /app/out/full/ .
RUN --mount=type=cache,target=/root/.cache/turbo pnpm turbo build --filter=@unique-ag/${APP_NAME}... \
 && pnpm --filter=@unique-ag/${APP_NAME} deploy --prod out

FROM node:26.9.0-trixie-slim AS runner
ARG APP_NAME
WORKDIR /app
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends dumb-init ca-certificates \
 && rm -rf /var/lib/apt/lists/* /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx
ENV NODE_ENV=production
COPY --from=builder --chown=node:node /app/services/${APP_NAME}/dist ./dist
COPY --from=builder --chown=node:node /app/services/${APP_NAME}/drizzle ./drizzle
COPY --from=builder --chown=node:node /app/services/${APP_NAME}/drizzle.config.ts ./drizzle.config.ts
COPY --from=builder --chown=node:node /app/out/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/out/package.json ./package.json
USER node
EXPOSE 9560
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "--enable-source-maps", "dist/main.js"]
