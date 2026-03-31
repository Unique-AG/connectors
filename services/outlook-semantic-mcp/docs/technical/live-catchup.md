<!-- confluence-page-id: 2061303823 -->
<!-- confluence-space-key: PUBDOC -->

# Live Catch-Up

Live catch-up is the real-time email ingestion pipeline. It receives Microsoft Graph change notifications the moment new mail arrives. The webhook is acknowledged immediately via RabbitMQ to meet Microsoft's strict 10-second response deadline; email fetching and ingestion happen inline in the consumer.

> **Operator summary:** Live catch-up runs automatically. States: `ready` → `running` → `ready`. If it fails, the recovery scheduler resets it within 5 minutes. If no activity occurs for 4 hours (e.g. missed webhook), the recovery scheduler also retriggers it. The watermark (a timestamp marking the most recent email processed) is used to fetch only newer emails.

## How It Works

Live catch-up operates in two stages: a **notification stage** (fast, synchronous) and an **ingestion stage** (inline, within the same consumer execution).

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
sequenceDiagram
    autonumber
    participant MSGraph as Microsoft Graph
    participant Controller as Webhook Controller
    participant AMQP as RabbitMQ
    participant Consumer as Live Catch-Up Consumer
    participant DB as PostgreSQL
    participant UniqueKB as Unique Knowledge Base

    Note over MSGraph,Controller: Stage 1 — Notification (must respond in < 10s)
    MSGraph->>Controller: POST /mail-subscription/notification
    Controller->>Controller: Validate clientState secret
    Controller->>Controller: Filter out deleted notifications
    Controller->>Controller: Group message IDs by subscriptionId
    Controller->>AMQP: Publish live-catch-up.execute (subscriptionId, messageIds[])
    Controller->>MSGraph: 202 Accepted

    Note over AMQP,UniqueKB: Stage 2 — Ingestion (inline)
    AMQP->>Consumer: Deliver message
    Consumer->>DB: Acquire lock on inbox_configurations row

    alt liveCatchUpState = running (recent heartbeat) OR watermark not yet set
        Consumer->>DB: Buffer messageIds in pendingLiveMessageIds
    else liveCatchUpState = ready (stale heartbeat) OR failed OR running (stale heartbeat)
        Consumer->>DB: Set liveCatchUpState = running
        Consumer->>MSGraph: GET /me/messages?$filter=lastModifiedDateTime ge {watermark}
        MSGraph->>Consumer: New/modified messages since watermark
        loop For each message
            Consumer->>UniqueKB: Ingest email directly (IngestEmailCommand)
            Consumer->>DB: Update newestLastModifiedDateTime watermark
        end
        Consumer->>DB: Flush pendingLiveMessageIds, set liveCatchUpState = ready
    end
```

**Stage 1 — Notification (synchronous):**

- The controller validates the `clientState` secret against `MICROSOFT_WEBHOOK_SECRET`
- `deleted` change notifications are discarded. Deletions are handled in two ways: when an entire folder is deleted, the [Directory Sync](./directory-sync.md) detects this via delta sync; when an individual email is deleted, the user first moves it to a folder marked `ignoreForSync` (e.g. Deleted Items), which generates a `created` event for that folder — the server detects the email is in an ignored folder and removes it from the knowledge base.
- Remaining message IDs are grouped by `subscriptionId` and published to RabbitMQ as a single batch
- `202 Accepted` is returned immediately — no email fetching happens in this stage

**Stage 2 — Ingestion (inline):**

- The consumer acquires a row-level lock on `inbox_configurations` to prevent concurrent processing
- It uses `newestLastModifiedDateTime` (the watermark) as the lower bound for a Graph query, ensuring only new or recently modified emails are fetched
- For each email returned, the consumer calls `IngestEmailCommand` directly — no intermediate queue is involved
- The watermark is advanced after every individual message
- After processing all fetched emails, any buffered pending messages are flushed the same way

## Live Catch-Up States

| State | Meaning |
|-------|---------|
| `ready` | Idle — ready to process the next notification |
| `running` | Actively fetching from Graph and ingesting messages inline |
| `failed` | An unhandled error occurred during processing |

**State transitions:**

- `ready` → `running`: Consumer acquires lock and watermark is set
- `running` → `ready`: Processing complete, pending messages flushed
- `running` / `ready` → `failed`: Unhandled error during execution
- `failed` → `ready`: Recovery scheduler resets state and retriggers (every 5 minutes)

**Pending message buffer:**

When `liveCatchUpState = running` with a recent heartbeat, new incoming notifications are appended to `pendingLiveMessageIds` instead of being dropped. After the active consumer finishes, it flushes the buffer by ingesting each pending ID directly. This ensures no notifications are lost during high-frequency mail delivery.

**Watermark not yet set:**

If `newestLastModifiedDateTime` is `null` (full sync has not initialized the watermarks yet), incoming notifications are also buffered. They are flushed once the watermarks are initialized.

## Relation to Full Sync

Live catch-up and full sync run **concurrently** after a user connects:

- Live catch-up buffers notifications until full sync has initialized the watermarks (`newestLastModifiedDateTime`). After that, both pipelines ingest in parallel.
- Once full sync initializes `newestLastModifiedDateTime`, live catch-up takes ownership of that watermark and updates it on every notification.
- Live catch-up ingestion activity (calling the Unique KB ingestion API directly) contributes to the in-progress count that full sync monitors during `waiting-for-ingestion`.

## Recovery

A background scheduler runs every **5 minutes** and checks for live catch-ups that need recovery:

| Condition | Threshold | Action |
|-----------|-----------|--------|
| `liveCatchUpState = ready`, heartbeat stale | 4 hours | Retrigger — Microsoft does not always send webhooks for events such as category changes |
| `liveCatchUpState = failed`, heartbeat stale | 5 minutes | Reset to `ready` and retrigger |
| `liveCatchUpState = running`, heartbeat stale | 5 minutes | Reset to `ready` and retrigger |

For subscription-level failures (e.g. `subscriptionRemoved`), see [Subscription Management](./subscription-management.md#Recovery).

## Related Documentation

- [Subscription Management](./subscription-management.md) - Subscription lifecycle, `reconnect_inbox`, `delete_inbox_data`
- [Directory Sync](./directory-sync.md) - Folder sync and email delete detection
- [Full Sync](./full-sync.md) - Historical batch ingestion and watermark initialisation
- [Flows](./flows.md#Live-Catch-Up:-Webhook-Driven-Email-Ingestion) - Live catch-up sequence diagram
- [Configuration](../operator/configuration.md) - `MICROSOFT_WEBHOOK_SECRET` and related env vars
