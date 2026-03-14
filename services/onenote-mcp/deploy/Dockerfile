FROM node:24-alpine AS base
RUN corepack enable

FROM base AS builder
WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig.json ./
COPY packages/ packages/
COPY services/onenote-mcp/ services/onenote-mcp/

RUN pnpm install --frozen-lockfile
RUN pnpm turbo build --filter=@unique-ag/onenote-mcp

FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production

COPY --from=builder /app/services/onenote-mcp/dist ./dist
COPY --from=builder /app/services/onenote-mcp/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/services/onenote-mcp/node_modules ./services/onenote-mcp/node_modules

EXPOSE 9543

CMD ["node", "dist/main.js"]
