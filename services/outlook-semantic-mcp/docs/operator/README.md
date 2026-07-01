<!-- confluence-page-id: 2065694735 -->
<!-- confluence-space-key: PUBDOC -->

# Outlook Semantic MCP — Operator Manual

## Overview

The Outlook Semantic MCP Server exposes MCP tools that allow AI assistants to search and retrieve email content. In `microsoft_graph_and_unique_api` mode (the default), it also runs background pipelines that ingest emails from connected Microsoft 365 accounts into the Unique knowledge base via Microsoft Graph webhooks and RabbitMQ. In `microsoft_graph` mode, no ingestion runs — emails are queried live from Microsoft Graph.

For end-user and administrator documentation, see the [Outlook Semantic MCP Overview](../README.md).

## Architecture

The connector runs as a **single pod** that handles MCP tool requests, stores state in PostgreSQL, and authenticates users via Microsoft Entra ID. The deployment mode (`MCP_BACKEND`) determines whether emails are ingested into the Unique knowledge base or queried live from Microsoft Graph.

### Mode A — `microsoft_graph_and_unique_api`

After a user connects, the pod creates a Microsoft Graph webhook subscription and runs background pipelines (full sync and live catch-up) that ingest emails into the Unique knowledge base. `search_emails` runs semantic search against the knowledge base and KQL keyword search against Microsoft Graph in parallel, then merges the results. RabbitMQ decouples webhook receipt from email processing so the service can respond to Microsoft within the required deadline.

```mermaid
flowchart LR
    MCPClient["User's MCP Client"]
    Kong["Kong Gateway"]
    OutlookMCP["Outlook Semantic MCP Pod"]
    PostgreSQL["PostgreSQL"]
    RabbitMQ["RabbitMQ"]
    UniqueKB["Unique Knowledge Base"]
    MSGraph["Microsoft Graph API"]
    EntraID["Microsoft Entra ID"]

    MCPClient -->|"MCP tool requests"| Kong
    Kong -->|"MCP + Webhooks"| OutlookMCP
    OutlookMCP --> PostgreSQL
    OutlookMCP -->|"Enqueue / consume\n(email sync)"| RabbitMQ
    OutlookMCP -->|"Ingest + semantic search"| UniqueKB
    OutlookMCP -->|"Fetch emails, KQL search,\ndrafts, contacts"| MSGraph
    MSGraph -->|"Webhooks"| Kong
    OutlookMCP -->|"OAuth"| EntraID
```

### Mode B — `microsoft_graph`

No ingestion pipeline runs — no webhook subscriptions are created and no email content is written to the Unique knowledge base. `search_emails` queries Microsoft Graph directly using KQL keyword search. The Unique knowledge base is still required for scope management and to attach email attachments to outgoing drafts. RabbitMQ remains a required infrastructure dependency but is not part of the email data path.

```mermaid
flowchart LR
    MCPClient["User's MCP Client"]
    Kong["Kong Gateway"]
    OutlookMCP["Outlook Semantic MCP Pod"]
    PostgreSQL["PostgreSQL"]
    RabbitMQ["RabbitMQ"]
    UniqueKB["Unique Knowledge Base"]
    MSGraph["Microsoft Graph API"]
    EntraID["Microsoft Entra ID"]

    MCPClient -->|"MCP tool requests"| Kong
    Kong -->|"MCP"| OutlookMCP
    OutlookMCP --> PostgreSQL
    OutlookMCP -.->|"Required\n(not used for email)"| RabbitMQ
    OutlookMCP -->|"Scope management,\nattachments"| UniqueKB
    OutlookMCP -->|"Live KQL search,\ndrafts, contacts"| MSGraph
    OutlookMCP -->|"OAuth"| EntraID
```

## Quick Start

### Unique SaaS

After [granting admin consent](https://login.microsoftonline.com/organizations/adminconsent?client_id=ba326974-edcf-49ef-bf7a-74b3e0ea450a) (see [Authentication](./authentication.md#unique-saas) for why this is needed), provide the following to Unique Support or Solution Engineering:

- [ ] **Backend mode** — controls how email search works; see [Deployment Modes](./configuration.md#Deployment-Modes) for the full trade-offs:
  - `microsoft_graph` — live KQL search directly against Microsoft Graph; no email ingestion into Unique KB; lighter deployment
  - `microsoft_graph_and_unique_api` *(default)* — emails ingested into Unique KB; semantic search merged with live KQL results; heavier but richer

- [ ] **Delegated access scan** — only relevant if your organization uses Exchange mailbox delegation (i.e. users who have been granted access to another user's mailbox or folders); see [`DELEGATED_ACCESS_SCAN`](./configuration.md#DELEGATED_ACCESS_SCAN):
  - `disabled` *(default)* — no delegation scanning
  - `full_access_only` — Full Access (Read & Manage) grants via Exchange admin
  - `granular_access` — folder-level grants (e.g. shared Inbox or RFQ folder); subsumes `full_access_only`

Unique will configure your deployment using the following process:

1. Create a Zitadel service account for the MCP in your organization — see [Zitadel Service Account](./configuration.md#Zitadel-Service-Account) for the required permissions
2. Deploy the MCP to your tenant and configure it according to your needs — see [Deployment Guide](./deployment.md)
3. The MCP server endpoint URL will be sent to you once everything is configured

For full configuration capabilities, see the [Configuration Guide](./configuration.md).

### Self-Hosted

Follow these steps to go from zero to a running deployment:

1. **Register Microsoft Entra ID application** — Create an app registration with the required delegated permissions. See [Authentication Guide](./authentication.md).
2. **Create Zitadel service account** — Create a service user and assign the required permissions. Required for both `cluster_local` and `external` auth modes in both Mode A and Mode B. See [Zitadel Service Account](./configuration.md#Zitadel-Service-Account) for setup and [required permissions](./configuration.md#Service-Account-Permissions).
3. **Provision infrastructure** — Set up PostgreSQL 17+, RabbitMQ 4+, and a Kubernetes namespace. See [Deployment — Prerequisites](./deployment.md#Prerequisites).
4. **Create Kubernetes secrets** — Generate cryptographic secrets and store them as Kubernetes Secrets. See [Deployment — Required Secrets](./deployment.md#Required-Secrets).
5. **Configure Helm values** — Create a `values.yaml` with your secrets, Microsoft client ID, and Unique API endpoints. See [Configuration Guide](./configuration.md).

   > **Key decisions:** Set `MCP_BACKEND` (see [Deployment Modes](./deployment.md#Deployment-Modes)) and optionally `DELEGATED_ACCESS_SCAN` (see [Configuration](./configuration.md#DELEGATED_ACCESS_SCAN)).

6. **Deploy with Helm** — Install the chart. See [Deployment — Install](./deployment.md#Install).
7. **Security checklist** — Before going to production, verify the following:

   - [ ] `ENCRYPTION_KEY` is a cryptographically random 64-character hex string
   - [ ] `AUTH_HMAC_SECRET` is a cryptographically random 64-character hex string
   - [ ] `MICROSOFT_WEBHOOK_SECRET` is a cryptographically random 128-character string
   - [ ] See [Configuration — Required Secrets](./configuration.md#Required-Secrets) for generation commands and format details
   - [ ] All secrets stored in Kubernetes Secrets (not ConfigMaps)
   - [ ] TLS termination configured at ingress
   - [ ] Network policies restrict pod-to-pod communication
   - [ ] Log aggregation in place (tokens are not logged)
   - [ ] Monitoring alerts configured for authentication failures

   For the full security architecture, see [Security Documentation](../technical/security.md). For a breakdown of what data is stored where, see [Data Classification and Flow](../technical/security.md#Data-Classification-and-Flow).

8. **Verify** the deployment is working:
   1. Check the OAuth metadata endpoint: `curl https://<your-domain>/.well-known/oauth-authorization-server`
   2. Connect with an MCP client and complete the OAuth flow
   3. *(Mode A only)* Call `verify_inbox_connection` to confirm the webhook subscription is `active`, draft a test email to the connected account, wait a moment, then use `search_emails` to confirm it appears
   5. *(Mode B only)* Draft a test email to the connected account, call `search_emails` with a simple KQL query to confirm it returns results from Microsoft Graph
9. **(Optional) Enable delegated access** — If your organization uses Exchange mailbox delegation (Full Access or folder-level), set `delegatedAccessScan` to `full_access_only` or `granular_access` in your Helm values. Both users (delegate and owner) must connect their accounts for delegated search to work. See [Configuration — DELEGATED_ACCESS_SCAN](./configuration.md#DELEGATED_ACCESS_SCAN).

## Scaling Considerations

- **Directory sync** processes a maximum of 10 users per scheduled run (every 5 minutes, configurable via `DIRECTORY_SYNC_CRON_SCHEDULE`). For large deployments with many connected users, account for the fact that folder sync updates are distributed across multiple runs.

## Documentation

| Document | Description |
|----------|-------------|
| [Deployment](./deployment.md) | Kubernetes deployment, Helm charts, database migration |
| [Configuration](./configuration.md) | Environment variables, Helm values, service auth modes |
| [Authentication](./authentication.md) | Microsoft Entra ID app registration, OAuth setup |
| [Local Development](./local-development.md) | Setting up a development environment |
| [Disaster Recovery](./disaster-recovery.md) | Recovery runbook for DB, RabbitMQ, and Knowledge Base failures |
| [FAQ](../faq.md) | Frequently asked questions and common mistakes |
