<!-- confluence-page-id: 1789329445 -->
<!-- confluence-space-key: ~624ebe8d45ece00069ce737e -->
<!-- confluence-space-key: ~624ebe8d45ece00069ce737e -->
# Why RabbitMQ is Needed

## Overview

RabbitMQ serves as the message broker in the Teams MCP service, enabling asynchronous processing of Microsoft Graph webhook notifications. This document explains why this architectural decision is essential.

## The Problem

Microsoft Graph sends webhook notifications when:
- A new meeting transcript is created
- A subscription needs reauthorization (lifecycle event)
- A subscription has been removed

Microsoft **requires** webhook endpoints to respond within **10 seconds**, or it considers the delivery failed and retries. However, processing these notifications involves:

1. Database lookups to find the subscription
2. Multiple Microsoft Graph API calls (fetch meeting, transcript, recording)
3. User resolution against the Unique platform
4. Content ingestion (uploading VTT transcripts and MP4 recordings)

This processing can take **30+ seconds**, far exceeding Microsoft's timeout requirement.

## The Solution: Message Queue

```
Microsoft Graph → Webhook Controller → RabbitMQ → Transcript Service → Unique
     (10s max)         (immediate)      (queue)      (async processing)
```

RabbitMQ decouples **webhook reception** from **processing**:

1. **Webhook Controller** receives the notification, validates `clientState`, publishes to RabbitMQ, and returns `202 Accepted` immediately
2. **RabbitMQ** durably stores the message until a consumer processes it
3. **Transcript Service** consumes messages and performs the slow processing asynchronously

## Key Benefits

### 1. Microsoft Webhook Compliance
- Respond to webhooks in milliseconds, not seconds
- Avoid Microsoft retry storms from failed deliveries
- Maintain reliable subscription health

### 2. Reliability via Dead Letter Exchange
Messages that fail processing are routed to a Dead Letter Exchange (DLX):

```
Main Exchange → Queue → Consumer (fails) → Dead Letter Exchange → Dead Queue
```

This allows:
- Failed messages to be inspected and debugged
- Manual or automated retry of failed messages
- No data loss even during processing failures

### 3. Scalability
- Multiple service replicas can consume from the same queues
- Load is distributed across consumers automatically
- Burst traffic (many meetings ending simultaneously) is buffered in queues

### 4. Backpressure Handling
- If processing slows down, messages accumulate in RabbitMQ (not in memory)
- Service remains responsive to new webhooks
- Processing catches up when resources are available

## Message Flow

### Change Notifications (transcript.created)

```
POST /transcript/notification
    ↓
Validate clientState
    ↓
amqp.publish(MAIN_EXCHANGE, 'unique.teams-mcp.transcript.change-notification.created', payload)
    ↓
Return 202 Accepted
    ↓
... later, asynchronously ...
    ↓
@RabbitSubscribe(queue: 'unique.teams-mcp.transcript.change-notifications')
    ↓
Fetch meeting, transcript, recording from Graph API
    ↓
Ingest into Unique platform
```

### Lifecycle Notifications (reauthorization, removal)

```
POST /transcript/lifecycle
    ↓
Validate clientState
    ↓
amqp.publish(MAIN_EXCHANGE, 'unique.teams-mcp.transcript.lifecycle-notification.*', payload)
    ↓
Return 202 Accepted
    ↓
... later, asynchronously ...
    ↓
@RabbitSubscribe(queue: 'unique.teams-mcp.transcript.lifecycle-notifications')
    ↓
Renew or remove subscription via Graph API
```

## Queue Configuration

For exchange and queue details, see [Architecture - RabbitMQ](./architecture.md#rabbitmq).

## Why Not Alternatives?

### In-Memory Queue (e.g., Bull, Agenda)
- Not durable across restarts
- Lost messages on crashes
- Single-node limitation

### Database-Based Queue
- Higher latency
- More complex locking
- Polling overhead

### Direct Processing
- Cannot meet 10-second webhook deadline
- No retry capability
- No backpressure handling

## Conclusion

RabbitMQ is essential infrastructure for the Teams MCP service. It enables the service to:
- Meet Microsoft's strict webhook response requirements
- Process notifications reliably with retry capability
- Scale horizontally without code changes
- Handle burst traffic gracefully

Without a message queue, the service would fail to maintain Microsoft Graph subscriptions and lose transcript data during processing failures.

## Related Documentation

- [Architecture](./architecture.md) - System components and infrastructure
- [Security](./security.md) - Encryption, PKCE, and threat model
- [Flows](./flows.md) - User connection, subscription lifecycle, transcript processing
- [Token and Authentication](./token-auth-flows.md) - Token types, validation, refresh flows
- [Microsoft Graph Permissions](./permissions.md) - Required scopes and least-privilege justification

## Standard References

- [Microsoft Graph Webhooks](https://learn.microsoft.com/en-us/graph/webhooks) - Webhook documentation
- [RabbitMQ Documentation](https://www.rabbitmq.com/documentation.html) - RabbitMQ official docs
- [AMQP 0-9-1 Model](https://www.rabbitmq.com/tutorials/amqp-concepts.html) - AMQP concepts
