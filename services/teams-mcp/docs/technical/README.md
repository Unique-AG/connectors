<!-- confluence-page-id: 1802633247 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

This section contains detailed technical documentation for developers and architects working with the Teams MCP Server.

**Note:** The Teams MCP Server is both an MCP server and a connector — it exposes **14 MCP tools** (8 chat/messaging + 6 transcript/KB) that AI clients invoke on demand, and once a user connects their account, it automatically ingests meeting transcripts into the Unique knowledge base in the background. This contrasts with pure connector-style servers which ingest data silently without exposing tools.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | System components, infrastructure, and data model |
| [Flows](./flows.md) | Sequence diagrams for user connection, subscriptions, and processing |
| [Permissions](./permissions.md) | Microsoft Graph permissions with least-privilege justification |
| [Security](./security.md) | Encryption, authentication, and threat model |
| [Subscription Management](./subscription-management.md) | Transcript-ingestion webhook subscription lifecycle (create, renew, status, removal) |
| [Tools](./tools.md) | Full reference for all 14 MCP tools (8 chat/messaging + 6 transcript/KB) |
| [FAQ](../faq.md) | Frequently asked questions |
