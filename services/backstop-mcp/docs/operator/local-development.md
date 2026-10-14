<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Run the server on your machine against a real Backstop tenant and a local PostgreSQL. The service is
a Python project driven by [uv](https://docs.astral.sh/uv/), not by pnpm or turbo.

> **Writes are real.** There is no Backstop sandbox in this setup. Write tools create, change, and
> delete records in whichever tenant `BACKSTOP_BASE_URL` points at, as the user you log in with.

## Prerequisites

| Tool | Why |
|---|---|
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.14 (pinned in `.python-version`) and the dependencies |
| Docker | Local PostgreSQL, and the test suite starts a PostgreSQL container |
| A Backstop login with a personal API token | To log in through the form. The login must be a Backstop system user |

## 1. Start PostgreSQL

The repository's `docker-compose.yaml` runs PostgreSQL 17 on port `9001` with user and password
`postgres`. It does not create this service's database, so create it once:

```bash
# from the repository root
docker compose up -d postgres
docker compose exec postgres createdb -U postgres backstop_mcp
```

## 2. Configure

```bash
cd services/backstop-mcp
cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`uv run` creates the environment first if it does not exist yet.

In `.env`, set at least:

```bash
APP_ENV=development
PUBLIC_BASE_URL=http://localhost:9010
BACKSTOP_BASE_URL=https://<firm>.backstopsolutions.com
BACKSTOP_MCP_ENCRYPTION_KEY=<the key printed above>
```

`.env.example` already points `DB_*` at the compose database and documents most other variables.
`APP_ENV=development` allows the `http://localhost` issuer, which production refuses. The full list
is in [Configuration](./configuration.md).

## 3. Install, migrate, run

```bash
uv sync --locked
uv run alembic upgrade head
uv run backstop-mcp
```

`backstop-mcp` loads `.env` and serves on `PORT` (default `9010`):

| URL | What |
|---|---|
| `http://localhost:9010/mcp` | MCP endpoint (streamable HTTP) |
| `http://localhost:9010/.well-known/oauth-authorization-server` | OAuth discovery |
| `http://localhost:9010/backstop/login` | Login form (reached through the OAuth flow, not directly) |
| `http://localhost:9010/health` | Process is up |
| `http://localhost:9010/ready` | PostgreSQL is reachable |
| `http://localhost:9010/metrics` | Prometheus metrics |

## 4. Connect a client

Use any MCP client that supports OAuth over streamable HTTP, for example the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector
```

Point it at `http://localhost:9010/mcp`. The client registers itself, your browser opens the login
form, and after you submit your Backstop username and API token the client is connected. Start with a
read tool such as `list_system_users` or `search_organizations`.

## Migrations

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # create
uv run alembic downgrade -1                          # roll back one
```

Alembic reads the same `DB_URL` / `DATABASE_URL` / `DB_*` variables as the server. Migrations cover this service's
`backstop_credentials` table and the shared `mcp_auth_*` tables.

## Tests, Lint, Types

The same checks the `[CI] Python` workflow runs:

```bash
pnpm install --frozen-lockfile                  # once, from the repository root, for biome
cd services/backstop-mcp
uv sync --locked
uv run ruff format --check . && uv run ruff check .
pnpm exec biome check . --no-errors-on-unmatched
uv run basedpyright                             # do not pass `.`, that type-checks .venv
uv run pytest                                   # needs Docker running
```

`uv run ruff format .` applies the formatting, and `uv run pytest tests/features/auth -k refresh`
runs a subset.

Feature tests mock the Backstop HTTP API and do not need PostgreSQL. App, auth, and database tests
start a PostgreSQL container.

In a fresh git worktree, run `uv sync` first. Without a `.venv`, basedpyright resolves no imports and
reports thousands of errors that are not real. See the repository's `DEVELOP.md`, "Python Services".

## Changing the Code

Read [`AGENT_README.md`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/AGENT_README.md)
before adding or changing a feature. It sets the layout every feature follows and the rules tests
enforce:

- a tool is registered by adding it to [`server/tools/registry.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/server/tools/registry.py),
- nothing under `features/` imports `server/`,
- every cached provider is listed in `teardown.PROVIDERS`.

How the Backstop REST API itself behaves (records, filters, paging, write payloads, errors) is in
the [Backstop Data Model](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/docs/technical/backstop-data-model/README.md).

`agent-explore/` holds developer scripts for reading the live API and Backstop's help centre. It is
not part of the shipped server.

## Troubleshooting

| Startup error | Cause |
|---|---|
| `PUBLIC_BASE_URL must be this service's externally-reachable URL in production` | `APP_ENV` is not set to `development`, and the default is `production` |
| `BACKSTOP_MCP_ENCRYPTION_KEY must be a Fernet key` | The key in `.env` is empty (as in `.env.example`) or malformed. Generate one as in [step 2](#2.-Configure) |
| `DB_URL not set; missing required fields: ...` | Neither `DB_URL` nor `DATABASE_URL` is set, and some of `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` are missing |
| PostgreSQL's `database "backstop_mcp" does not exist` | The `createdb` command in [step 1](#1.-Start-PostgreSQL) was skipped |

## Related

- [Operator Guide](./README.md)
- [Overview](../README.md)
- [Configuration](./configuration.md)
- [Authentication](./authentication.md)
- [Developer documentation](../README.md#Developer-documentation): code layout,
  [`AGENT_README.md`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/AGENT_README.md), and the
  [Backstop Data Model](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/docs/technical/backstop-data-model/README.md)
