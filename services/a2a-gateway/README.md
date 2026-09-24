# A2A gateway

Optional bidirectional A2A gateway for Unique. The architecture and protocol contracts are in [`docs`](./docs/README.md).

## Local development

Use the PostgreSQL and RabbitMQ instances from `monorepo/.local`; the gateway intentionally does not start separate infrastructure.

From the workspace root, start the monorepo development stack and create the gateway database once:

```sh
(cd monorepo/.local && docker compose up -d)
docker compose -f monorepo/.local/docker-compose.yaml exec postgres bash -lc \
  'psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''a2a-gateway'\''" | grep -q 1 || createdb -U postgres a2a-gateway'
```

Then initialise Absurd and start the gateway:

```sh
cp connectors/services/a2a-gateway/.env.example connectors/services/a2a-gateway/.env
set -a; . connectors/services/a2a-gateway/.env; set +a
pnpm --dir connectors --filter @unique-ag/a2a-gateway db:absurd:init
pnpm --dir connectors --filter @unique-ag/a2a-gateway dev
```

Start the local core services as usual; they declare the `unique.event-bus` RabbitMQ exchange consumed by the gateway. Workers are enabled by default. Set `WORKER_ENABLED=false` only on an intentionally API-only replica when another replica consumes the workflow queue. `/health/live` reports process liveness. `/health/ready` requires the shared PostgreSQL and RabbitMQ, the worker unless explicitly disabled, and all configured Unique services.
