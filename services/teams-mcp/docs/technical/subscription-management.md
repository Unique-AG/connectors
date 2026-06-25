<!-- confluence-page-id: 2399993877 -->
<!-- confluence-space-key: PUBDOC -->

# Teams MCP - Subscription Management

A Microsoft Graph webhook subscription must be active for **meeting transcripts to be ingested automatically**. The server manages the full lifecycle — creation, renewal, expiry detection, and removal — and exposes it through three tools: [`start_kb_integration`](./tools.md#start_kb_integration), [`stop_kb_integration`](./tools.md#stop_kb_integration), and [`verify_kb_integration_status`](./tools.md#verify_kb_integration_status).

!!! note "Transcripts only"
    This subscription covers **meeting-transcript ingestion** into the Unique knowledge base. Chat and channel messages are read live through Microsoft Graph and are never subscribed to or ingested. The [`ingest_meeting`](./tools.md#ingest_meeting) tool does not require a subscription — it pulls a single meeting's transcript on demand.

## Subscription Creation

Unlike a background-only connector, ingestion is **opt-in per user**: a subscription is created when the user calls `start_kb_integration` (it is not created automatically on connect).

1. `start_kb_integration` invokes `SubscriptionCreateService.subscribe()`
2. The service creates a Graph subscription for the resource `users/{providerUserId}/onlineMeetings/getAllTranscripts` with `changeType: created`
3. The subscription is registered with `notificationUrl` (transcript notifications) and `lifecycleNotificationUrl` (lifecycle events), authenticated with a `clientState` webhook secret
4. The subscription record is stored in the `subscriptions` table (`internalType: 'transcript'`) with the Graph subscription id and its expiration time

The expiration time is set to the next occurrence of the configured off-peak UTC hour (see [`MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC`](#configuration) below), giving a predictable renewal window.

## Subscription Renewal

Subscriptions are renewed via Microsoft Graph lifecycle notifications:

- Microsoft sends a `reauthorizationRequired` lifecycle notification before the subscription expires (the exact timing varies; Microsoft does not guarantee a fixed window, but notifications arrive at least ~15 minutes before expiry)
- The lifecycle webhook controller enqueues the event, and `SubscriptionReauthorizeService.reauthorize()` PATCHes `/subscriptions/{id}` with a new `expirationDateTime`
- The new expiration is again the next configured UTC expiration hour, and the `subscriptions` record is updated to match

The database is the source of truth: a `reauthorizationRequired` notification for a subscription id that is not in the `subscriptions` table is ignored.

## Subscription Status

The `verify_kb_integration_status` tool reports one of four statuses:

| Status | Meaning | Action |
|--------|---------|--------|
| `active` | Subscription valid, more than 15 minutes until expiry | None required |
| `expiring_soon` | 15 minutes or less until expiry | Renewal is automatic; no action needed |
| `expired` | Subscription has lapsed | Call `start_kb_integration` |
| `not_configured` | No subscription exists | Call `start_kb_integration` |

## `start_kb_integration`

Safe to call at any time — it is idempotent and inspects the existing subscription before acting:

- **No subscription exists:** creates a new subscription (`created`)
- **Valid subscription, more than 15 minutes until expiry:** returns `already_active`, no changes made
- **Valid subscription, expiring within 15 minutes:** returns `expiring_soon`, no changes made — automatic renewal is either in progress or imminent, so a new subscription is deliberately not forced (avoids racing an in-flight renewal)
- **Expired subscription:** deletes the lapsed record and creates a fresh subscription (`created`)

## `stop_kb_integration`

Removes the transcript-ingestion subscription:

- Deletes the `subscriptions` record (the source of truth), then issues `DELETE /subscriptions/{id}` to Microsoft Graph
- Returns `removed` when a record was deleted, or `not_found` when nothing was active

Removal stops future automatic ingestion. **Previously ingested transcripts remain in the Unique knowledge base** — `stop_kb_integration` does not delete content. To resume automatic ingestion, call `start_kb_integration` again.

!!! note "Graph deletion is best-effort"
    Because the database is the source of truth, the local record is removed first. If the subsequent Graph `DELETE` fails, the orphaned Graph subscription is harmless: any later notification it produces is discarded because no matching record exists in the `subscriptions` table.

## Subscription Failure Handling

Microsoft Graph sends lifecycle notifications when a subscription's state changes. The server handles the two it acts on automatically; all other lifecycle events are discarded.

| Condition | What Happens | User Action Required? |
|-----------|-------------|----------------------|
| `reauthorizationRequired` lifecycle event | Server automatically PATCHes the subscription with a new expiration time | No |
| `subscriptionRemoved` lifecycle event | Server deletes the local `subscriptions` record (Graph has already removed it) — automatic ingestion stops | Yes — user must call `start_kb_integration` to re-subscribe |
| Other lifecycle events (e.g. `missed`) | Discarded and logged; no recovery action is taken | No (but missed transcripts are not retroactively recovered — see note) |
| Subscription expired (missed renewal) | `verify_kb_integration_status` reports `expired`; no notifications are received | Yes — user must call `start_kb_integration` |
| No subscription exists | `verify_kb_integration_status` reports `not_configured` | Yes — user must call `start_kb_integration` |

!!! warning "No automatic gap recovery"
    Teams MCP does not run a catch-up pass for transcripts missed while a subscription was lapsed or after a `missed` lifecycle event. To ingest a specific meeting whose transcript was not captured, use [`ingest_meeting`](./tools.md#ingest_meeting) with the meeting's join URL.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` | `3` | Hour of day (UTC, 0–23) at which scheduled subscription expirations are set. Choose an off-peak hour to avoid disrupting incoming notifications. |
| `MICROSOFT_WEBHOOK_SECRET` | (required) | Secret sent as the subscription `clientState` and validated on every incoming notification. |
| `SELF_URL` / `MICROSOFT_PUBLIC_WEBHOOK_URL` | `SELF_URL` | Public URL Microsoft Graph posts notifications to. |

## Related Documentation

- [Tools](./tools.md#start_kb_integration) - `start_kb_integration`, `stop_kb_integration`, `verify_kb_integration_status`, and `ingest_meeting` tool reference
- [Flows](./flows.md) - Subscription lifecycle and transcript-processing sequence diagrams
- [Permissions](./permissions.md) - The `OnlineMeetingTranscript.Read.All` / `OnlineMeetingRecording.Read.All` admin-consent scopes the subscription depends on
- [Configuration](../operator/configuration.md) - `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` and webhook settings
</content>
</invoke>
