# Technical Reference

## Overview

This section contains detailed technical documentation for developers and architects working with the Teams MCP Server.

**Note:** The Teams MCP Server is a connector-style MCP server, not a traditional MCP server. It does not provide tools, prompts, resources, or other MCP capabilities. Once connected, it automatically ingests meeting transcripts into the Unique knowledge base in the background.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | System components, infrastructure, and data model |
| [Flows](./flows.md) | Sequence diagrams for user connection, subscriptions, and processing |
| [Permissions](./permissions.md) | Microsoft Graph permissions with least-privilege justification |
| [Security](./security.md) | Encryption, authentication, and threat model |
| [Token and Authentication](./token-auth-flows.md) | OAuth token lifecycle and validation |
| [Why RabbitMQ](./why-rabbitmq.md) | Message queue design rationale |
| [FAQ](../faq.md) | Frequently asked questions |
