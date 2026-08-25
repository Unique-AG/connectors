<!-- confluence-page-id: 2063335449 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

This section contains detailed technical documentation for developers and architects working with the Outlook Semantic MCP Server.

**Note:** The Outlook Semantic MCP Server is both an MCP server and a connector — it exposes 10 mail MCP tools (plus 4 debug-mode tools), and 8 more calendar tools when `CALENDAR_INTEGRATION` is enabled. AI clients invoke those on demand, and once a user connects their account, the server automatically syncs their emails into the Unique knowledge base in the background. This contrasts with pure connector-style servers (like Sharepoint Connector) which ingest data silently without exposing tools.

## Documentation


| Document                                                | Description                                                                    |
| ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [Architecture](./architecture.md)                       | System components, modules, database schema, and RabbitMQ topology             |
| [Flows](./flows.md)                                     | Sequence diagrams for OAuth connection, email sync, and subscription lifecycle |
| [Permissions](./permissions.md)                         | Microsoft Graph permissions with least-privilege justification                 |
| [Security](./security.md)                               | Encryption, OAuth 2.1 with PKCE, token rotation, and threat model              |
| [Subscription Management](./subscription-management.md) | Subscription lifecycle, renewal, status, and failure handling                  |
| [Features](./features.md)                               | User-facing features, what's supported, what's not, and setup steps (including delegated access) |
| [Tools](./tools.md)                                     | Full reference for mail tools, debug tools, and the calendar tool list         |
| [Calendar integration](./calendar-integration.md)       | Live Outlook calendar tools, ID namespaces, re-consent, example prompts        |
| [FAQ](../faq.md)                                        | Frequently asked questions                                                     |
