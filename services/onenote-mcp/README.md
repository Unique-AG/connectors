# OneNote MCP

A NestJS-based microservice that synchronizes Microsoft OneNote notebooks with the Unique knowledge base via the Microsoft Graph API. It periodically polls connected users' OneNote content and ingests pages as searchable, access-controlled documents into Unique.

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [MCP Tools](#mcp-tools)
- [Development](#development)
- [Deployment](#deployment)
- [Observability](#observability)

## Quick Start

```bash
# Install dependencies
pnpm install

# Copy environment template
cp .env.example .env

# Run database migrations
pnpm db:migrate

# Start development server
pnpm dev
```

## How It Works

### Synchronization

The service runs a **configurable cron job** (default: every 15 minutes) that iterates over all connected users and syncs their OneNote content into the Unique knowledge base.

The sync uses a **two-level delta-based** approach to minimize Microsoft Graph API calls:

1. **Level 1 -- driveItem delta (coarse filter):** OneNote notebooks are stored as OneDrive driveItems. The service calls `GET /me/drive/root/delta` to detect which notebooks changed since the last sync. Delta tokens are persisted per user in the `delta_state` database table.

2. **Level 2 -- page content upsert (fine-grained):** For each changed notebook, the service traverses sections and pages, fetching HTML content and upserting it into the Unique knowledge base. Content keys (`onenote:{userId}:{pageId}`) and `lastModifiedDateTime` ensure only changed pages are re-ingested.

### Content Ingestion

Each OneNote page is ingested as an HTML content item into Unique:

- **Content key:** `onenote:{userId}:{pageId}`
- **URL:** The page's `oneNoteWebUrl`, so references open directly in OneNote
- **Metadata:** `createdDateTime`, `lastModifiedDateTime`, notebook name, section name
- **Scope hierarchy:** mirrors the OneNote structure -- `{root} / {notebook} / {section} / [pages]`

### Permissions

Notebook permissions are resolved from Microsoft Graph and mapped to Unique scope accesses:

- **Owner** receives Read/Write/Manage access
- **Shared users** (direct or via group expansion) receive Read access
- Section sub-scopes inherit access from the parent notebook scope
- Groups are expanded via `GET /groups/{groupId}/members` and each member is resolved to a Unique user by email

### Authentication

The service uses **delegated** Microsoft OAuth (per-user tokens), since the OneNote Graph API does not support app-only authentication. This follows the same pattern as the `teams-mcp` service:

- OAuth 2.0 authorization code flow with PKCE
- Encrypted token storage in PostgreSQL
- Automatic token refresh via middleware
- Required scopes: `Notes.ReadWrite.All`, `Files.Read.All`, `User.Read`

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Scheduler (Cron)                                               │
│  Triggers sync for all connected users at configurable interval │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐     ┌──────────────────────────────────┐
│  OneNoteSyncService  │────▶│  OneNoteGraphService             │
│  Per-user sync       │     │  Microsoft Graph API calls       │
│  orchestration       │     │  (notebooks, sections, pages,    │
│                      │     │   driveItem delta, permissions)  │
└──────┬───────────────┘     └──────────────────────────────────┘
       │
       ├──▶ OneNoteDeltaService      (delta token persistence)
       ├──▶ OneNotePermissionsService (Graph → Unique access mapping)
       │
       ▼
┌──────────────────────┐     ┌──────────────────────────────────┐
│  UniqueContentService│────▶│  Unique Knowledge Base API       │
│  UniqueScope Service │     │  (scopes, content, storage)      │
│  UniqueUser Service  │     │                                  │
└──────────────────────┘     └──────────────────────────────────┘
```

### Key Services

| Service | Responsibility |
|---------|---------------|
| `SchedulerService` | Manages the cron job, iterates users with configurable concurrency |
| `OneNoteSyncService` | Orchestrates per-user sync: delta detection, notebook traversal, content ingestion |
| `OneNoteGraphService` | All Microsoft Graph API calls (notebooks, sections, pages, permissions, delta) |
| `OneNoteDeltaService` | Manages delta tokens for incremental sync, handles 410 Gone fallback |
| `OneNotePermissionsService` | Resolves Graph permissions to Unique scope accesses |
| `UniqueContentService` | Content upsert and HTML upload to Unique storage |
| `UniqueScopeService` | Scope creation and access management in Unique |
| `UniqueUserService` | User resolution by email in Unique |

### Database Schema

The service uses PostgreSQL via Drizzle ORM with these tables:

| Table | Purpose |
|-------|---------|
| `user_profiles` | Stores connected user profiles and encrypted OAuth tokens |
| `delta_state` | Persists Microsoft Graph delta tokens per user for incremental sync |
| `oauth_clients` | OAuth client registrations |
| `oauth_sessions` | Active OAuth sessions |
| `tokens` | Access/refresh token pairs |
| `authorization_codes` | OAuth authorization codes |

## Configuration

Copy `.env.example` to `.env` and configure the following:

### Required Variables

| Variable | Description |
|----------|-------------|
| `SELF_URL` | Base URL for OAuth callbacks |
| `DATABASE_URL` | PostgreSQL connection string |
| `MICROSOFT_CLIENT_ID` | Azure AD application client ID |
| `MICROSOFT_CLIENT_SECRET` | Azure AD application client secret |
| `AUTH_HMAC_SECRET` | 64-char hex secret for JWT signing |
| `ENCRYPTION_KEY` | 64-char hex secret for AES-GCM token encryption |

### Sync Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_INTERVAL_CRON` | `*/15 * * * *` | Cron expression for sync frequency |
| `SYNC_CONCURRENCY` | `3` | Max concurrent user syncs |
| `SYNC_PAGE_BATCH_SIZE` | `20` | Pages to process per batch |

### Unique API Configuration

**External Mode** (for external deployments):
```env
UNIQUE_SERVICE_AUTH_MODE=external
UNIQUE_API_BASE_URL=http://localhost:8092/public/
UNIQUE_SERVICE_EXTRA_HEADERS={"authorization":"Bearer <app-key>","x-app-id":"<app-id>","x-user-id":"<user-id>","x-company-id":"<company-id>"}
```

**Cluster Local Mode** (for in-cluster deployments):
```env
UNIQUE_SERVICE_AUTH_MODE=cluster_local
UNIQUE_API_BASE_URL=http://chat.namespace.svc:PORT/public/chat/
UNIQUE_INGESTION_SERVICE_BASE_URL=http://ingestions.namespace.svc:PORT
UNIQUE_SERVICE_EXTRA_HEADERS={"x-company-id":"<company-id>","x-user-id":"<user-id>"}
```

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Logging level (debug, info, warn, error) |
| `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | `60` | Access token TTL |
| `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | `2592000` | Refresh token TTL (30 days) |
| `UNIQUE_ROOT_SCOPE_ID` | - | Root scope ID under which to create notebook folders (required) |
| `UNIQUE_USER_FETCH_CONCURRENCY` | `5` | Concurrent user resolution limit |

### Generating Secrets

```bash
# Generate 64-char hex secret (for AUTH_HMAC_SECRET, ENCRYPTION_KEY)
openssl rand -hex 32
```

## MCP Tools

The service exposes 7 MCP tools for AI assistants and users to interact with OneNote data:

### Search

| Tool | Description |
|------|-------------|
| `search_onenote` | Semantic search over synced OneNote pages. Supports filters for notebook name, section name, date range, and score threshold. |

### Content Creation & Modification

| Tool | Description |
|------|-------------|
| `create_onenote_notebook` | Creates a new notebook for the authenticated user via Graph API. |
| `create_onenote_page` | Creates a new page in a specified section with HTML content. |
| `update_onenote_page` | Modifies existing page content (append, prepend, or replace). |

### Sync Control

| Tool | Description |
|------|-------------|
| `start_onenote_sync` | Triggers an immediate sync for the current user. |
| `stop_onenote_sync` | Stops sync by clearing the user's delta state. |
| `verify_onenote_sync_status` | Returns current sync status, last sync time, and any errors. |

## Development

### Prerequisites

- Node.js 20+
- pnpm
- PostgreSQL 17
- Microsoft Azure AD application with required permissions

### Available Scripts

| Script | Description |
|--------|-------------|
| `pnpm dev` | Start development server |
| `pnpm build` | Build for production |
| `pnpm test` | Run unit tests |
| `pnpm test:e2e` | Run end-to-end tests |
| `pnpm test:coverage` | Run tests with coverage |
| `pnpm db:generate` | Generate database migrations |
| `pnpm db:migrate` | Apply database migrations |
| `pnpm style` | Check code style |
| `pnpm style:fix` | Fix code style issues |

### Microsoft Azure AD Setup

Register an application in Azure AD with the following API permissions (delegated):

| Permission | Reason |
|-----------|--------|
| `Notes.ReadWrite.All` | Read and write all OneNote notebooks, sections, and pages |
| `Files.Read.All` | DriveItem delta tracking and notebook permission resolution |
| `User.Read` | Read user profile for identity |
| `offline_access` | Obtain refresh tokens for long-lived sessions |

## Deployment

### Docker

The service includes a Dockerfile following the same multi-stage build pattern as other connectors in this monorepo.

```bash
docker build -t onenote-mcp .
docker run -p 9543:9543 --env-file .env onenote-mcp
```

### Kubernetes (Helm)

Helm charts follow the same structure as `teams-mcp` and can be found in `deploy/helm-charts/`.

## Observability

The service includes comprehensive observability via OpenTelemetry:

- **Logging**: Structured JSON logs via Pino with correlation IDs
- **Metrics**: OpenTelemetry instrumentation for Graph API calls (request count, latency, errors)
- **Tracing**: Distributed tracing via OpenTelemetry

Configure with environment variables:
```env
OTEL_SERVICE_NAME=onenote-mcp
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
```
