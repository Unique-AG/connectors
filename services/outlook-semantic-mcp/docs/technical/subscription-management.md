<!-- confluence-page-id: 2065072136 -->
<!-- confluence-space-key: PUBDOC -->

# Subscription Management

A Microsoft Graph webhook subscription must be active for live catch-up to function. The server manages the full lifecycle — creation, renewal, expiry detection, and removal.

## Subscription Creation

A subscription is created automatically when a user connects:

1. The `user-authorized` event fires after OAuth
2. `SubscriptionCreateService` creates a Graph subscription for `users/{id}/messages` with `changeType: created`
3. The subscription record is stored in the `subscriptions` table with its expiration time
4. A `subscription-created` event triggers the full sync

## Subscription Renewal

Subscriptions are renewed via Microsoft Graph lifecycle notifications:

- Microsoft sends a `reauthorizationRequired` notification 15–45 minutes before expiration
- The server responds by PATCHing the subscription with a new `expirationDateTime`
- Subscriptions renew to the next configured UTC expiration hour (set by `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC`)

If a `subscriptionRemoved` notification arrives (Microsoft removed the subscription), the subscription and inbox_configurations records are deleted. The user must reconnect via `reconnect_inbox`.

## Subscription Status

The `verify_inbox_connection` tool reports one of four statuses:

| Status | Meaning | Action |
|--------|---------|--------|
| `active` | Subscription valid, more than 15 minutes until expiry | None required |
| `expiring_soon` | Less than 15 minutes until expiry | Renewal is automatic; no action needed |
| `expired` | Subscription has lapsed | Call `reconnect_inbox` |
| `not_configured` | No subscription exists | Call `reconnect_inbox` |

## `reconnect_inbox`

Safe to call at any time — it is idempotent:

- If a valid subscription exists with more than 15 minutes until expiry: returns `already_active`, no changes made
- If a valid subscription exists but expires within 15 minutes: returns `expiring_soon`, no changes made (renewal is automatic)
- If subscription is expired: deletes the old subscription and inbox_configurations records and creates a new subscription
- If no subscription exists: creates a new subscription

Calling `reconnect_inbox` triggers a full sync when a new subscription is created. If the subscription is `already_active` or `expiring_soon`, no full sync is triggered.

## `remove_inbox_connection`

Removes the mailbox connection entirely:

- Removes directory sync data and the root scope from the Unique knowledge base
- Deletes the Graph webhook subscription
- Deletes the `inbox_configurations` record (stops full sync and live catch-up)

Because the root scope is removed, all previously ingested email content for that user is also removed from the Unique knowledge base. To resume ingestion, call `reconnect_inbox`.

## Recovery

| Condition | Recovery |
|-----------|---------|
| `subscriptionRemoved` lifecycle event | Subscription and inbox_configurations deleted; user must call `reconnect_inbox` |
| `reauthorizationRequired` lifecycle event | Server automatically renews the subscription |

## Related Documentation

- [Live Catch-Up](./live-catchup.md) - Webhook-driven ingestion that depends on an active subscription
- [Directory Sync](./directory-sync.md) - Folder sync that also depends on an active connection
- [Full Sync](./full-sync.md) - Historical batch ingestion triggered on subscription creation
- [Flows](./flows.md#subscription-creation-and-renewal-lifecycle) - Subscription lifecycle sequence diagram
- [Tools](./tools.md#verify_inbox_connection) - `verify_inbox_connection`, `reconnect_inbox`, `remove_inbox_connection` tool reference
- [Configuration](../operator/configuration.md) - `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` and related env vars
