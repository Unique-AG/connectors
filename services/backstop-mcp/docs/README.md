<!-- confluence-page-id: 2813722682 -->
<!-- confluence-space-key: PUBDOC -->

## Getting Started

| You want to | Read |
|---|---|
| Connect your MCP client and log in | [Authentication: User Connection Flow](./operator/authentication.md#User-Connection-Flow) |
| Deploy the server, on Unique SaaS or self-managed, and configure it | [Operator Guide](./operator/README.md) |
| Understand how it works, what it can read and write, and every tool | [Technical Reference](./technical/README.md) |
| Find a quick answer | [FAQ](./faq.md) |
| Change the server's code | [Local Development](./operator/local-development.md), then the [developer documentation](#Developer-documentation) on GitHub |

## Overview

Backstop MCP is an MCP server that lets AI assistants read and write a firm's
[Backstop](https://www.backstopsolutions.com/) CRM through the Backstop REST API. It covers
organizations, people, activities (notes, meetings, calls, emails, documents, tasks), the
opportunity pipeline, funds and investor accounts, custom fields, and saved Report Center reports,
through 44 MCP tools.

Every tool call acts as the signed-in user. Each user connects once with their own Backstop
username and personal API token; the server never uses a shared service account, so a user sees
and changes exactly what Backstop allows them to.

Backstop has no OAuth of its own, so this server is the OAuth 2.1 authorization server for its MCP
clients. It hosts a small login form, checks the submitted credential against Backstop, stores it
encrypted, and issues its own short-lived MCP tokens. See [Authentication](./operator/authentication.md).

## Quick Summary

| | |
|---|---|
| **What it does** | 44 tools: 27 read-only, 17 that create, change, or delete CRM records |
| **Who it acts as** | The connected user, with their own Backstop credential |
| **Deployment** | One Python (FastMCP) container on Kubernetes, installed with a Helm chart |
| **Durable state** | PostgreSQL only: OAuth clients and tokens, each user's encrypted Backstop credential, and recent login attempts |
| **Not needed** | No message queue, no Unique knowledge base, no Zitadel service account, no ingestion |
| **CRM data at rest** | None. Backstop data is fetched live per call. Reference catalogs are cached in memory, and report results are held in memory for up to an hour so a slow build can be collected |

## Requirements

### Backstop

| Requirement | Details |
|---|---|
| **Backstop tenant** | Reachable over HTTPS from the cluster, either on the tenant's own host or on the shared `api.backstopsolutions.com` |
| **Personal API token per user** | Created in Backstop under *Main Menu › System Tools › Administrative › Update Your Profile*, API Security section. The login form takes this token, never a password |
| **Matching system user** | The Backstop login must belong to a Backstop system user. Login is refused otherwise, because the activities a user logs are authored as that system user |

### Platform

| Requirement | Details |
|---|---|
| **Kubernetes + Helm** | The chart depends on Unique's `base` chart, which renders the Deployment, Service, Gateway API route, NetworkPolicy, and migration hook. The route and NetworkPolicy are off by default; the deployment's overlay turns them on |
| **PostgreSQL** | One database. Schema migrations run as a Helm hook (`alembic upgrade head`) |
| **Public HTTPS URL** | MCP clients and users' browsers must reach the server; the URL is the OAuth issuer (`PUBLIC_BASE_URL`) |

## What It Can Do

| Feature | Read | Write |
|---|---|---|
| [Contacts](./technical/features.md#Contacts) | Look up, search firm-wide, roster of an organization, employment history | Create, update, delete; add and end employment; edit addresses |
| [Activities and Tasks](./technical/features.md#Activities-and-Tasks) | Firm-wide or per-party search, full detail and attachments, last activity per party, tasks | Log notes, meetings, calls, tasks; attach documents and email files; update; delete |
| [Opportunities](./technical/features.md#Opportunities) | A party's deals with stage history, firm-wide search and counts, deals by id | Create, update (including stage moves), delete, backfill stage history |
| [Products and Accounts](./technical/features.md#Products-and-Accounts) | Products, a party's holdings, a product's investors, dated time series, subscriptions and redemptions | None |
| [Custom Fields](./technical/features.md#Custom-Fields) | Definitions, layout groups, values on records | Write values on people, organizations, and opportunities |
| [Saved Reports](./technical/features.md#Saved-Reports) | Run a saved Report Center report by name | None |
| [Backstop Links](./technical/features.md#Backstop-Links) | Build and parse links to the Backstop web app | None |

See [Features](./technical/features.md) for the questions each feature answers and how it behaves.

## How It Works

```mermaid
flowchart LR
    Client["MCP client<br/>(e.g. Unique chat)"]
    Browser["User's browser"]
    Server["Backstop MCP pod"]
    DB[("PostgreSQL")]
    Backstop["Backstop REST API"]

    Client -->|"OAuth 2.1 + MCP over HTTP"| Server
    Browser -->|"One-time login form<br/>(username + API token)"| Server
    Server -->|"OAuth rows,<br/>encrypted credentials"| DB
    Server -->|"HTTPS, as the user<br/>(Basic auth + token header)"| Backstop
```

1. The user adds the server to their MCP client. The client registers itself and starts an OAuth
   flow.
2. The browser opens the server's login form. The user enters their Backstop username and personal
   API token. The server checks them against Backstop and finds the user's system-user record.
3. The server stores the credential encrypted, and gives the client a 15-minute access token and a
   30-day refresh token.
4. Each tool call loads that user's credential and calls Backstop as them.

See [Architecture](./technical/architecture.md) for components and request flow.

## Limitations

| Limitation | Details |
|---|---|
| **No shared service account** | Every user needs their own Backstop login and API token |
| **5 concurrent requests per user** | Backstop's own limit. The server queues a user's requests to stay within it, per pod |
| **Deletes are permanent** | Backstop has no recycle bin. The four delete tools show the record and ask the user to confirm when the client supports elicitation; otherwise they delete without asking |
| **Creates are not idempotent** | Repeating a create call makes a second record |
| **Read-only areas** | Funds, accounts, flows, reports, and catalogs (tags, categories, sources, users) cannot be written |
| **File size** | `attach_file` accepts files up to 3,096,576 bytes (about 2.95 MiB) |
| **Search ceiling** | Backstop's activity search stops at 10,000 rows; larger sets come back with `coverage.ceiling_hit` set |
| **Key employee** | The server rejects `is_key_employee` on person and employment writes; set it in the Backstop UI |

## Related Documentation

- [FAQ](./faq.md)
- [Operator Guide](./operator/README.md)
  - [Authentication](./operator/authentication.md)
  - [Configuration](./operator/configuration.md)
  - [Disaster Recovery](./operator/disaster-recovery.md)
  - [Local Development](./operator/local-development.md)
- [Technical Reference](./technical/README.md)
  - [Architecture](./technical/architecture.md)
  - [Features](./technical/features.md)
  - [Tools](./technical/tools.md)

### Developer documentation

These pages live in the repository and are read on GitHub. They are for developers changing the
server, not for using or operating it.

| Document | What it covers |
|---|---|
| [Service README](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/README.md) | Code layout, the layering rule, and the steps for adding a feature or tool |
| [`AGENT_README.md`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/AGENT_README.md) | The full guide to how features are structured, and the rules every feature follows |
| [Backstop Data Model](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/docs/technical/backstop-data-model/README.md) | How the Backstop REST API behaves, and Backstop's standard records, fields and errors |
| [`DEVELOP.md`](https://github.com/Unique-AG/connectors/blob/main/DEVELOP.md#python-services) | Repository-wide commands for Python services |

## Standard References

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [OAuth 2.1](https://oauth.net/2.1/)
- [RFC 7636: PKCE](https://datatracker.ietf.org/doc/html/rfc7636)
- [RFC 7591: Dynamic Client Registration](https://datatracker.ietf.org/doc/html/rfc7591)
- [Backstop help centre: REST API](https://backstopsolutions.elevio.help/en/articles/1018)
