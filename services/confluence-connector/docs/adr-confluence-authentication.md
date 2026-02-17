# ADR: Confluence Connector Authentication Strategy

**Ticket:** [UN-16934](https://unique-ch.atlassian.net/browse/UN-16934) | **Status:** Proposed | **Date:** 2026-02-10

## Context

The confluence-connector authenticates with the Confluence REST API to sync content. It runs as a **background service** (no interactive user) and must support both **Cloud** and **Data Center**.

## Confluence Cloud Options

| | OAuth 2.0 (3LO) | Basic Auth (API Token) |
|---|---|---|
| **How** | One-time admin consent in browser, then auto-refresh tokens | Admin creates API token at [id.atlassian.com](https://id.atlassian.com/manage/api-tokens), configures email + token |
| **Header** | `Bearer {access_token}` | `Basic base64(email:api_token)` |
| **Scopes** | Fine-grained (`read:confluence-content.all`, `search:confluence`, etc.) | None — inherits all user permissions |
| **Token expiry** | Access token ~1h, refresh token rotates (90-day inactivity) | Never (unless manually revoked) |
| **Security** | High — scoped, rotating | Low — unscoped, static |
| **Atlassian stance** | **Recommended** for production ([docs](https://developer.atlassian.com/cloud/confluence/security-overview/)) | Scripts only — [non-compliant](https://developer.atlassian.com/platform/marketplace/security-requirements/) for production |
| **Tied to user account** | No (app identity) | Yes |
| **Complexity** | High — callback endpoint, token refresh, persistent storage for refresh tokens | Minimal — config only |
| **API base URL** | `api.atlassian.com/ex/confluence/{cloudId}/...` | `{domain}.atlassian.net/wiki/rest/api/...` |

## Confluence Data Center Options

| | PAT | OAuth 2.0 (App Links) | Basic Auth |
|---|---|---|---|
| **How** | Admin creates token in DC user settings | Admin configures Application Link in DC admin | Username + password in config |
| **Header** | `Bearer {PAT}` | `Bearer {access_token}` | `Basic base64(user:pass)` |
| **Scopes** | None — inherits user permissions | Configurable via App Links | None — inherits user permissions |
| **Token expiry** | Configurable or never | Configurable | N/A |
| **Security** | Medium — dedicated token | High — app-level identity | Low — actual password |
| **Tied to user account** | Yes | No | Yes |
| **Complexity** | Minimal — config only | High — OAuth flow, token persistence, RSA signing | Minimal — config only |
| **DC version** | 7.9+ | All | All |

## Current State: confluence-connector v1 (monorepo)

The existing v1 connector uses the simplest auth methods for both targets:

- **Cloud**: Basic Auth — `email` + `api_token` via `CONFLUENCE_CLOUD_USER` / `CONFLUENCE_CLOUD_TOKEN` env vars
- **Data Center**: PAT via `CONFLUENCE_PAT` env var, falling back to Basic Auth via `CONFLUENCE_USERNAME` / `CONFLUENCE_PASSWORD`

No OAuth is used for Confluence API calls. OAuth (client credentials) is only used for authenticating with the Unique ingestion API via Zitadel.

## Key Trade-off

OAuth (3LO for Cloud, App Links for DC) gives scoped, user-independent access but requires **persistent storage for refresh tokens** — in-memory is not enough because tokens rotate (old token invalidated on each refresh, lost on pod restart). Lightweight options: Kubernetes Secret via K8s API, file on PVC, or external vault.

Static tokens (API Token for Cloud, PAT for DC) are config-only and stateless, but tied to a user account and unscoped.

## Decision

*To be decided after team review.*
