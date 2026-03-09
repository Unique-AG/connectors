FROM node:24-alpine AS base
RUN corepack enable

FROM base AS builder
WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig.json ./
COPY packages/ packages/
COPY services/onenote-connector/ services/onenote-connector/

RUN pnpm install --frozen-lockfile
RUN pnpm turbo build --filter=@unique-ag/onenote-connector

FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production

COPY --from=builder /app/services/onenote-connector/dist ./dist
COPY --from=builder /app/services/onenote-connector/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/services/onenote-connector/node_modules ./services/onenote-connector/node_modules

EXPOSE 9543

CMD ["node", "dist/main.js"]
