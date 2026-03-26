<!-- confluence-page-id: 2063335449 -->
<!-- confluence-space-key: PUBDOC -->

# Technical Reference

## Overview

This section contains detailed technical documentation for developers and architects working with the Outlook Semantic MCP Server.

**Note:** The Outlook Semantic MCP Server is both an MCP server and a connector — it exposes 10 MCP tools (plus 4 debug-mode tools) that AI clients invoke on demand, and once a user connects their account, it automatically syncs their emails into the Unique knowledge base in the background. This contrasts with pure connector-style servers (like Sharepoint Connector) which ingest data silently without exposing tools.

## Documentation


| Document                                                | Description                                                                    |
| ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [Architecture](./architecture.md)                       | System components, modules, database schema, and RabbitMQ topology             |
| [Flows](./flows.md)                                     | Sequence diagrams for OAuth connection, email sync, and subscription lifecycle |
| [Permissions](./permissions.md)                         | Microsoft Graph permissions with least-privilege justification                 |
| [Security](./security.md)                               | Encryption, OAuth 2.1 with PKCE, token rotation, and threat model              |
| [Tools](./tools.md)                                     | Full reference for all 10 MCP tools (plus 4 debug-mode tools)                  |
| [Full Sync](./full-sync.md)                             | Historical batch email ingestion mechanics                                     |
| [Live Catch-Up](./live-catchup.md)                      | Webhook-driven real-time email ingestion                                       |
| [Subscription Management](./subscription-management.md) | Graph subscription lifecycle, reconnect, and remove                            |
| [Directory Sync](./directory-sync.md)                   | Folder sync, delete detection, and search filtering                            |
| [FAQ](../faq.md)                                        | Frequently asked questions                                                     |
