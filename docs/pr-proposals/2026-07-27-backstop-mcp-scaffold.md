# PR Proposal

## Ticket
UN-22647

## Title
feat(backstop-mcp): scaffold FastMCP service with OAuth and deploy

## Description
- Add `services/backstop-mcp`: FastMCP server with OAuth credential bridging (hosted Backstop login form → encrypted per-user credentials in Postgres), structlog + OTel metrics, and an authenticated `get_system_info` example tool.
- Wire Alembic migrations, Dockerfile, and Helm (base chart + Postgres/migration hook); accept Helm-injected `DATABASE_URL` (rewriting libpq `sslmode` for asyncpg).
- Register the service in release-please, commitizen scopes, and per-service CI.
