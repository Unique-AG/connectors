<!-- confluence-page-id: 2813460614 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Technical reference for developers and architects working with Backstop MCP. For deployment and
configuration, see the [Operator Guide](../operator/README.md). For a short introduction, see the
[overview](../README.md).

Backstop MCP is a pure MCP server: it exposes 44 tools that AI clients call on demand. It does not
sync or index Backstop data. Apart from short-lived in-memory caches and the caller's own system-user
record saved at login, every call reads or writes Backstop live, as the connected user.

## Documentation

| Document | What it covers |
|---|---|
| [Architecture](./architecture.md) | Components, HTTP surface, request lifecycle, party resolution, the Backstop client, paging, caching, persistence, observability |
| [Features](./features.md) | What the server can do, feature by feature: the questions each answers, its behaviour, and what is not supported |
| [Tools](./tools.md) | One line per tool, with the file that implements it and what it returns |
| [Backstop Data Model](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/docs/technical/backstop-data-model/README.md) | For developers changing the server: how the Backstop REST API behaves, and Backstop's standard records, fields and errors |
| [Authentication](../operator/authentication.md) | OAuth, the login form, token lifetimes, reconnecting, credential encryption |
| Security | [Security checklist](../operator/README.md) (section 7) for a self-managed install; [Login Throttling](../operator/authentication.md#Login-Throttling) and [Encryption Key](../operator/authentication.md#Encryption-Key); what is logged in [Architecture: Logs](./architecture.md#Logs) |
| Permissions | Every call runs as the connected user, and Backstop applies that user's own permissions; the server has no permission model of its own. See [Authentication: How a Tool Call Authenticates](../operator/authentication.md#How-a-Tool-Call-Authenticates) and [Features: Safeguards](./features.md#Safeguards) |
| [FAQ](../faq.md) | Common questions |

## Source

| Path | Contents |
|---|---|
| [`src/backstop_mcp/`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp) | The server |
| [`server/tools/registry.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/server/tools/registry.py) | The registered tools |
| [`server/instructions.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/server/instructions.py) | The instructions every MCP client receives |
| [`config.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/config.py) | Every setting |
| [`packages/mcp-credential-auth`](https://github.com/Unique-AG/connectors/tree/main/packages/mcp-credential-auth) | Shared OAuth server, token storage, login throttling |
| [`deploy/helm-charts/backstop-mcp`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/deploy/helm-charts/backstop-mcp) | Helm chart |
| [`AGENT_README.md`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/AGENT_README.md) | How features are structured, and the rules for adding one |
