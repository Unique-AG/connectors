<!-- confluence-page-id: 1802633247 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

This section contains detailed technical documentation for developers and architects working with the Teams MCP Server.

**Note:** The Teams MCP Server exposes **8 MCP tools** that AI clients invoke on demand to read, search, and send Teams chat and channel messages. Every call is served live from the Microsoft Graph API — **nothing is copied into the Unique knowledge base**.

Deployments that additionally enable transcript capture (`UNIQUE_INTEGRATION=enabled`) register four more tools and run an asynchronous ingestion pipeline. That capability is documented in the [Recordings & Transcripts - Technical Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2399993877/Recordings+Transcripts+-+Technical+Manual).

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | System components, infrastructure, and data model |
| [Flows](./flows.md) | Sequence diagrams for user connection, OAuth, token refresh, and chat tools |
| [Permissions](./permissions.md) | Microsoft Graph permissions with least-privilege justification |
| [Security](./security.md) | Encryption, authentication, and threat model |
| [Tools](./tools.md) | Full reference for the 8 chat and messaging tools |
| [FAQ](../faq.md) | Frequently asked questions |
