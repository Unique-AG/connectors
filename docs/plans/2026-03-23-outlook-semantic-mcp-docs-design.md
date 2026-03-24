# Design: Outlook Semantic MCP Documentation

**Ticket:** UN-16565

## Problem

`outlook-semantic-mcp` has no `docs/` folder — only a basic README and a deploy guide. There is no structured documentation for operators, developers, or end users covering setup, configuration, tool usage, architecture, or troubleshooting. The Jira ticket asks for: setup and configuration guide, tool usage documentation, architecture overview, troubleshooting guide, and API reference.

## Solution

### Overview

Mirror the Teams MCP documentation pattern exactly: write a full `docs/` folder in the `outlook-semantic-mcp` repo with markdown files, then publish those files as Confluence pages under the `PUBDOC` space using the same naming convention as Teams MCP (e.g. `Outlook Semantic MCP - Architecture`, `Outlook Semantic MCP - Configuration`, etc.).

The docs are structured for two audiences: **operators** (deploy, configure, maintain) and **developers/architects** (understand internals). Since `outlook-semantic-mcp` is a traditional MCP server (user-facing tools) — unlike Teams MCP which is connector-style — it gets three additional technical docs: `tools.md` (14-tool reference), `full-sync.md`, and `live-catchup.md`.

All pages carry a pre-release disclaimer consistent with Teams MCP.

### Architecture

**Repository structure:**

```
services/outlook-semantic-mcp/docs/
├── README.md                  ← overview, pre-release disclaimer, features, how it works
├── faq.md                     ← common questions
├── operator/
│   ├── README.md              ← operator manual index + infra requirements + deployment checklist
│   ├── authentication.md      ← Entra ID app registration, permissions, consent flows
│   ├── configuration.md       ← all env vars, Helm values, service auth modes
│   ├── deployment.md          ← Kubernetes/Helm, secrets, health checks, monitoring
│   └── local-development.md  ← local setup, dev tunnels, webhook testing
└── technical/
    ├── README.md              ← technical manual index
    ├── architecture.md        ← components, DB schema, RabbitMQ, auth layers
    ├── flows.md               ← sequence diagrams: OAuth, subscription, email processing
    ├── permissions.md         ← Microsoft Graph permissions, least-privilege justification
    ├── security.md            ← encryption, PKCE, token rotation, threat model
    ├── tools.md               ← all 14 MCP tools with parameters and examples
    ├── full-sync.md           ← full sync mechanics, states, pause/resume/restart
    └── live-catchup.md        ← webhook-driven real-time ingestion, subscription lifecycle
```

**Confluence page hierarchy** (in `PUBDOC` space, nested same as Teams MCP):

```
Outlook-Semantic-MCP                             ← root (from docs/README.md)
├── Outlook Semantic MCP - Operator Manual       ← from docs/operator/README.md
│   ├── Outlook Semantic MCP - Authentication
│   ├── Outlook Semantic MCP - Configuration
│   ├── Outlook Semantic MCP - Deployment
│   └── Outlook Semantic MCP - Local Development
├── Outlook Semantic MCP - Technical Manual      ← from docs/technical/README.md
│   ├── Outlook Semantic MCP - Architecture
│   ├── Outlook Semantic MCP - Flows
│   ├── Outlook Semantic MCP - Permissions
│   ├── Outlook Semantic MCP - Security
│   ├── Outlook Semantic MCP - Tools
│   ├── Outlook Semantic MCP - Full Sync
│   └── Outlook Semantic MCP - Live Catch-Up
└── Outlook Semantic MCP - FAQ
```

### Error Handling

Not applicable — this is a documentation task with no runtime error handling concerns.

### Testing Strategy

Not applicable — no code is being written. Validation is done by reviewing each doc against the source code and the Teams MCP docs as a reference baseline.

## Out of Scope

- Updating the existing `README.md` or `deploy/README.md` at the root of `outlook-semantic-mcp`
- Documenting `outlook-mcp` (a separate service)
- Automating the Confluence publishing pipeline (pages are created manually via MCP tools)
- End-user documentation (how to use the MCP tools from a chat client perspective)
- Confluence Publishing (done manually by the user)

## Tasks

### Setup

1. **Create `docs/` folder skeleton** — Create all 15 empty markdown files in the correct directory structure under `services/outlook-semantic-mcp/docs/`. No content yet, just placeholder headings so the structure is visible and reviewable.

### Operator Docs

2. **Write `docs/README.md`** — Pre-release disclaimer, overview, feature list (email search, draft creation, contact lookup, folder management, subscription management, full sync, live catch-up), high-level how-it-works, requirements, and limitations. Mirror Teams MCP root page style.

3. **Write `docs/operator/README.md`** — Operator manual index, infrastructure requirements (Kubernetes 1.25+, PostgreSQL 17+, RabbitMQ 4+, Kong Gateway 3.x), and a deployment checklist covering infrastructure, Microsoft Entra ID, application, and verification steps.

4. **Write `docs/operator/authentication.md`** — Microsoft Entra ID app registration setup (Terraform and Azure Portal manual options), required delegated permissions with admin consent notes, understanding consent flows, redirect URI configuration, client secret management and rotation, webhook secret generation (128-char hex).

5. **Write `docs/operator/configuration.md`** — Complete environment variable reference (required secrets: DATABASE_URL, AMQP_URL, MICROSOFT_CLIENT_SECRET, MICROSOFT_WEBHOOK_SECRET, AUTH_HMAC_SECRET, ENCRYPTION_KEY; optional: LOG_LEVEL, token TTLs, UNIQUE_ROOT_SCOPE_PATH, UNIQUE_USER_FETCH_CONCURRENCY), full Helm values example, service auth modes (external vs cluster_local), Zitadel service account creation, root scope creation.

6. **Write `docs/operator/deployment.md`** — Prerequisites, Helm chart install commands, Kubernetes secrets creation with generation commands, database migration step, health check endpoints, Prometheus metrics and Grafana dashboards, alerting, network policies, Terraform module references.

7. **Write `docs/operator/local-development.md`** — Prerequisites (Node.js 20+, pnpm 9+, Docker 24+, Azure CLI, MCP Inspector), Docker Compose infrastructure setup, Microsoft Entra app registration for local dev, environment configuration with secret generation, webhook testing via Azure Dev Tunnels, available scripts, debugging common issues.

### Technical Docs

8. **Write `docs/technical/README.md`** — Technical manual index, note that this is a traditional MCP server (user-facing tools, contrast with connector-style like Teams MCP), links to all sub-pages.

9. **Write `docs/technical/architecture.md`** — High-level component diagram, module descriptions (OutlookMcpToolsModule, CategoriesModule, EmailManagementModule, SearchModule, DirectoriesSyncModule, SubscriptionModule, FullSyncModule, LiveCatchUpModule, MailIngestionModule, SyncRecoveryModule, MsGraphModule, DrizzleModule, McpOAuthModule, UniqueApiFeatureModule), PostgreSQL schema (all tables: user_profiles, subscriptions, oauth_sessions, oauth_clients, authorization_codes, tokens, inbox_configuration, directories, directories_sync), RabbitMQ exchanges and queues, authentication architecture (MCP OAuth 2.1 + PKCE layer vs Microsoft OAuth layer), token isolation design.

10. **Write `docs/technical/flows.md`** — Sequence diagrams for: user OAuth connection flow, Microsoft token refresh flow, subscription creation/renewal lifecycle, email ingestion via live catch-up, full sync trigger and progress flow, email draft creation flow.

11. **Write `docs/technical/permissions.md`** — Full table of all Microsoft Graph delegated permissions used (User.Read, Mail.Read, Mail.ReadWrite, Mail.Send, Contacts.Read, offline_access — verify against source), admin consent requirements, least-privilege justification per permission, explanation of why delegated (not application) permissions are used.

12. **Write `docs/technical/security.md`** — AES-256-GCM token encryption at rest, MCP token hashing, OAuth 2.1 with PKCE implementation, refresh token rotation with family-based revocation, webhook validation via clientState (128-char hex), secret rotation procedures for each secret (ENCRYPTION_KEY, AUTH_HMAC_SECRET, MICROSOFT_CLIENT_SECRET, MICROSOFT_WEBHOOK_SECRET), security checklist for operators.

13. **Write `docs/technical/tools.md`** — Full reference for all 14 MCP tools. For each tool: name, description, input parameters (name, type, required/optional, description), return shape, usage notes, and cross-references (e.g. `list_folders` → use folder IDs in `search_emails`). Tools: list_categories, search_emails, open_email_by_id, create_draft_email, lookup_contacts, list_folders, verify_inbox_connection, reconnect_inbox, remove_inbox_connection, run_full_sync, pause_full_sync, resume_full_sync, restart_full_sync, sync_progress. Note debug-mode-only restriction on sync tools.

14. **Write `docs/technical/full-sync.md`** — Full sync mechanics: what it does (batch historical email ingestion), trigger conditions, sync states (running/paused/finished/error), pause/resume/restart behaviour and when to use each, progress tracking via `sync_progress` (state, counters, date window, ingestion stats), inbox configuration filters (ignoredBefore, ignoredSenders, ignoredContents), debug-mode restriction on sync tools, relation to live catch-up.

15. **Write `docs/technical/live-catchup.md`** — Live catch-up mechanics: webhook-driven real-time email ingestion, how Microsoft Graph subscriptions work, subscription creation via `reconnect_inbox`, renewal lifecycle, expiry handling, `verify_inbox_connection` status values (active/expiring_soon/expired/not_configured), `remove_inbox_connection` behaviour, sync recovery on failed subscriptions, relation to full sync.

### FAQ

16. **Write `docs/faq.md`** — Cover: general (what kind of MCP server is this, what tools are available), authentication and permissions (admin consent, delegated vs application, client credentials), configuration (redirect URIs, webhook secret, encryption key), sync (full sync vs live catch-up, sync progress, filters), tool usage (search tips, draft attachments, folder IDs), security (token storage, encryption key rotation), deployment edge cases.
