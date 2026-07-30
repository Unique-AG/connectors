# Design: backstop-mcp scaffold

**Ticket:** UN-22647

## Problem

UN-22647 is the investigation/concept spike for a Backstop MCP wrapper: Capstone's Backstop CRM exposes a REST API (bidirectional, read + write-back, Party ID as the universal join key across Organizations/Persons/Accounts). Before domain tools can be designed, we need `backstop-mcp` scaffolded in `services/` with the same operational baseline as the rest of the MCP fleet (logging, config, metrics, health checks, deployment), plus the auth bridge required because Backstop has no native OAuth — only username + personal API token Basic auth.

## Solution

### Overview

Build on FastMCP idioms — a single `FastMCP` instance, `@mcp.tool` for tools, `@mcp.custom_route` for operational HTTP endpoints — rather than wrapping in FastAPI. Auth is an OAuth 2.1 authorization server (FastMCP `OAuthProvider`) whose "login" step is a hosted form that collects Backstop credentials, verifies them against Backstop, encrypts them at rest in Postgres, and mints MCP access/refresh tokens. Tool calls resolve the caller's stored credential and call Backstop as that user.

### Architecture

- `config.py` — `AppConfig` (env/port/log/public_base_url), `BackstopConfig` (API base URL only — no shared credentials), `DatabaseConfig` (Postgres URL; accepts Helm `DATABASE_URL` and rewrites libpq `sslmode` for asyncpg), `EncryptionConfig` (Fernet key for credential ciphertext).
- `logging.py` / `metrics.py` / `middleware.py` — structlog (JSON in prod), OTel Prometheus metrics at `/metrics`, request trace-context binding.
- `db/` — SQLAlchemy async engine + Alembic migrations for OAuth clients/tokens, pending authorizations, and encrypted Backstop credentials.
- `auth/` — `BackstopOAuthProvider` (login form → verify → store credential → auth code → tokens), credential crypto/store, and request-scoped credential resolution. Mid-session Backstop `401` revokes that subject's MCP token family so the client must re-login.
- `backstop_client.py` — per-user `httpx.AsyncClient` with Basic + `token: true` headers; auto-raises `BackstopAuthError` on 401 (and triggers token revocation on the tool path).
- `app.py` — wires FastMCP + OAuth provider, `/health`, `/probe`, `/metrics`, login routes, and the example `get_system_info` tool.
- `main.py` — dotenv + uvicorn on `AppConfig.port`.

### Error Handling

Config validation fails fast at startup. `/probe` returns healthy with an empty `checks` dict for now (shape ready for a DB/Backstop check later). Backstop `401` mid-session → `BackstopAuthError` + MCP token family revocation. Login-time unreachable Backstop → `BackstopUnreachableError` (shown as a form error, not "invalid credentials").

### Testing Strategy

- Config (including `DATABASE_URL` / `sslmode` rewrite), logging, probes, metrics.
- Auth provider, credential store/crypto, context resolution, login form.
- Backstop client + `get_system_info` tool (including 401 → revoke path) via testcontainers Postgres + respx.

## Out of Scope

- Broader Backstop domain tools (contacts, opportunities, accounts, activities, targeting).
- Party-ID data model / Backstop-specific schema beyond what auth needs.
- RabbitMQ or any event/write-back queue plumbing.
- Terraform-managed secrets beyond Helm/env wiring already in the chart.

## Tasks

1. Scaffold `pyproject.toml`, package layout, logging/metrics/middleware, health/probe routes.
2. Add Postgres + Alembic models for OAuth + encrypted credentials; Helm Postgres + migration hook.
3. Implement Backstop OAuth login form, credential verification/storage, and token lifecycle (including mid-session 401 revocation).
4. Add authenticated `get_system_info` example tool.
5. Dockerfile, Helm chart (base chart + Postgres), release-please/CI/commitizen wiring.
