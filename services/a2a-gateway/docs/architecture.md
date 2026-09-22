# Architecture

## Context

```mermaid
%%{init: {'theme': 'neutral'}}%%
flowchart LR
    subgraph Ext["External"]
        Client["A2A client"]
        Remote["Remote A2A agent"]
        Zitadel["Zitadel"]
    end

    subgraph GW["a2a-gateway (connectors, optional)"]
        Pub["Public A2A surface<br/>/a2a/*"]
        Mgmt["Management surface<br/>/management/*"]
        Int["Internal surface<br/>/internal/*"]
        Core["Task engine + absurd worker"]
        DB[("PostgreSQL")]
    end

    subgraph Unique["Unique core (monorepo)"]
        Kong["Kong"]
        Chat["node-chat"]
        SM["node-scope-management"]
        Ing["node-ingestion"]
        MQ[("RabbitMQ<br/>EVENT_BUS")]
        FE["Frontend"]
    end

    Client -.->|auth code + PKCE| Zitadel
    Client -->|"Bearer (human OAuth)"| Kong
    FE -->|Bearer| Kong
    Kong -->|"x-user-id / x-company-id / x-user-roles / x-client-id"| Pub & Mgmt
    Chat -->|"effective user headers"| Int
    Pub & Mgmt & Int --> Core
    Core --> DB
    Core -->|"x-user-id / x-company-id"| Chat & SM & Ing
    MQ -->|"unique.chat.*"| Core
    Core -->|"shared connection credentials"| Remote
```

## Ownership boundaries

| Concern | Owner |
| --- | --- |
| Spaces (assistants), chats, messages, files, elicitations, lifecycle, permissions, roles | **core** |
| Feature flag + entitlement evaluation | **core** (gateway trusts core's decision on its internal surface; re-checks on management/public surfaces via core) |
| JWT validation | **Kong** (never the gateway) |
| Publication of a native space (enabled, agent-card customisation, publication id) | **gateway** |
| Remote connections (URL, credential reference, negotiated capabilities) | **gateway** |
| A2A protocol state: contexts, tasks, artifacts, push-notification configs, mappings to chat/message ids | **gateway** |
| External-space execution routing (which space is external, which connection it uses) | **core** stores `executionProvider = A2A` + `connectionId`; gateway owns the connection |
| Agent execution, LLM, tools | **core** — the gateway never runs an LLM |

Rules:

- One published space = one logical A2A agent. Publication id is an opaque typeid; never expose the `assistantId`.
- External A2A spaces are **never** publishable (enforced in gateway DB constraint and core).
- Every invocation and every task/artifact read is authorised against core under the effective human; the catalog is a cache, not an authority.
- Gateway outage must not lose configuration: configuration lives in the gateway DB; core only keeps the reference (`connectionId`) and the space type.

## Components (gateway)

```mermaid
%%{init: {'theme': 'neutral'}}%%
flowchart TB
    subgraph Surfaces
        Pub["a2a-server module<br/>@a2a-js/sdk jsonRpcHandler<br/>agent cards, catalog"]
        Mgmt["management module<br/>publications, connections"]
        Int["internal module<br/>executions / cancel / elicitation-response / capabilities"]
    end

    subgraph Domain
        Exec["InboundExecutor<br/>(AgentExecutor)"]
        Out["OutboundRunner<br/>(@a2a-js/sdk Client, absurd task)"]
        Elic["ElicitationBridge"]
        Art["ArtifactTranslator<br/>text · data · file"]
        Push["PushNotificationSender"]
    end

    subgraph Infra
        Auth["KongIdentityGuard ·<br/>ClusterIdentityGuard"]
        UC["UniqueInternalClient<br/>(identity preserving)"]
        Bus["EventBusSubscriber<br/>(@golevelup/nestjs-rabbitmq)"]
        Store["PgTaskStore + repositories<br/>(drizzle)"]
        Wf["WorkflowModule (absurd)"]
        Sec["CredentialVault<br/>(aes-gcm-encryption)"]
    end

    Pub & Mgmt & Int --> Auth
    Pub --> Exec
    Int --> Out
    Bus --> Exec & Out
    Exec --> UC & Store & Elic & Art
    Out --> UC & Store & Elic & Art & Sec & Wf
    Mgmt --> Store & Sec & UC
    Wf --> Push
```

- **a2a-server**: `@a2a-js/sdk` `DefaultRequestHandler` + `jsonRpcHandler`, one handler instance, agent resolved from the `publicationId` path segment. `TaskStore` is our Postgres implementation scoped by `(companyId, userId)`.
- **Identity guards**: `KongIdentityGuard` (public + management: identity headers stamped by Kong), `ClusterIdentityGuard` (internal: headers from `node-chat`). No JWT handling in the gateway. `AUTH_MODE=development` relaxes both locally.
- **EventBusSubscriber**: one exclusive, auto-delete queue per replica bound to `EVENT_BUS` with `unique.chat.assistant-message.*`, `unique.chat.user-message.created`, `unique.chat.elicitation.*` (P-03). Events are matched to tasks/executions by `chatId`/`messageId`; snapshot updates are idempotent (monotonic `status_timestamp`); SSE relays happen on the replica holding the connection.
- **InboundExecutor**: maps A2A message → Unique chat message via `UniqueInternalClient`, relays bus events as task status/artifact events.
- **OutboundRunner**: invoked by core on the internal surface; runs as an absurd task: drive the remote agent via SDK `Client` (send/stream/poll/cancel), suspend on `awaitEvent` for elicitation answers, write results back into the Unique chat under the effective user.
- **ElicitationBridge**: `input-required`/`auth-required` ⇄ Unique `Elicitation` (FORM/URL).
- **WorkflowModule** (absurd, same image, `WORKER_ENABLED`): outbound runs, push-notification delivery with retries, reconciliation (deleted spaces, expired tasks, retention). Operators inspect it with habitat.

## Deployment

- Independently deployable Helm chart under `services/a2a-gateway/deploy`, same pattern as `teams-mcp`.
- Requires: PostgreSQL, RabbitMQ (platform event bus, read on `EVENT_BUS`), cluster-local reach to `node-chat`, `node-scope-management`, `node-ingestion`; egress to configured remote agents and push URLs only.
- **All external traffic enters through Kong**: `/a2a/agents/*/.well-known/agent-card.json` without auth; `/a2a/*` and `/management/*` with Kong JWT validation → identity headers (inbound `x-user-*` stripped). `/internal/*` is cluster-local only (NetworkPolicy from `node-chat`). The gateway has no public ingress of its own.
- No gateway → no A2A: core gates every A2A UI/API on `A2A_GATEWAY_URL` being configured **and** `/internal/capabilities` answering **and** the tenant feature/entitlement.
