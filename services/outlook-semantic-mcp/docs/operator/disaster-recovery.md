<!-- confluence-space-key: PUBDOC -->

# Disaster Recovery

This runbook covers recovery procedures for the three stateful components the Outlook Semantic MCP Server depends on: the local PostgreSQL database, RabbitMQ, and the Unique Knowledge Base. Each component has a distinct failure mode and recovery path.

Automatic recovery schedulers (a 2-minute full-sync retry and a 5-minute live catch-up) handle transient failures. The scenarios below require explicit operator action because the automatic schedulers are insufficient for total data loss.

Out of scope: partial database corruption, Microsoft Graph API outages, automated recovery scripts, and backup/restore procedures for the local database or RabbitMQ.

---

## Scenario 1: Local PostgreSQL Database Loss

### Symptoms

- Service fails to start with database connection errors in the logs.
- All MCP tools return errors or empty responses.
- No users appear connected — `verify_inbox_connection` returns `not_configured` for all users.

### Impact

The local database stores OAuth tokens, Microsoft Graph webhook subscriptions, and all sync state. Total loss of the database means:

- All users must re-authenticate via the OAuth flow.
- All Graph webhook subscriptions are orphaned in Microsoft's systems (they expire naturally after 3 days).
- All sync state (cursor positions, progress counters) is lost.
- Emails already ingested into the Unique Knowledge Base are **not** affected — they remain searchable.

### Recovery Steps

1. Restore or provision a new PostgreSQL instance and update `DATABASE_URL` in the Kubernetes secret if the connection string changed:

   ```bash
   kubectl create secret generic outlook-semantic-mcp-secrets \
     --namespace outlook-semantic-mcp \
     --from-literal=DATABASE_URL="postgresql://user:password@host:5432/outlook_semantic_mcp" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

2. Run database migrations to create the schema:

   ```bash
   kubectl exec -it deploy/outlook-semantic-mcp -n outlook-semantic-mcp -- pnpm run db:migrate
   ```

3. Restart the service pods to pick up the new database connection:

   ```bash
   kubectl rollout restart deploy/outlook-semantic-mcp -n outlook-semantic-mcp
   ```

4. Notify affected users that they must reconnect their inbox. Each user must:

   - Open the MCP tool interface.
   - Call `reconnect_inbox` (or follow the standard OAuth flow) to re-authenticate and re-create the Graph webhook subscription.

5. After reconnection, a full sync starts automatically. Monitor progress per user with `sync_progress`.

6. Because previously ingested emails remain in the Unique Knowledge Base, re-ingestion will overwrite existing content idempotently — file keys prevent duplicates.

**See also:** [Authentication](./authentication.md), [Deployment](./deployment.md#database-migration)

---

## Scenario 2: RabbitMQ Loss

### Symptoms

- Service logs show AMQP connection errors or failed message publish attempts.
- In-progress full syncs stall — `sync_progress` shows `fullSyncState: "running"` but `scheduledForIngestion` stops incrementing.
- Live catch-up stops processing new webhook notifications — recently received emails are not ingested.

### Impact

RabbitMQ carries in-flight sync trigger events between the service and its internal workers. Total loss means:

- Any full sync in progress at the time of failure is stalled. The sync state in the database is intact but the trigger event that drives the next batch is gone.
- Live catch-up events (incoming webhook notifications from Microsoft Graph) queued in RabbitMQ at the time of failure are lost.
- The local database and Unique Knowledge Base are **not** affected.
- No re-authentication is required.

### Recovery Steps

1. Restore or provision a new RabbitMQ instance and update `AMQP_URL` in the Kubernetes secret if the connection string changed.

2. Restart the service pods to reconnect to RabbitMQ:

   ```bash
   kubectl rollout restart deploy/outlook-semantic-mcp -n outlook-semantic-mcp
   ```

3. Enable debug mode on the deployment if it is not already enabled, by setting `MCP_DEBUG_MODE=enabled` in `mcpConfig.app.mcpDebugMode`. This exposes the `restart_full_sync` tool. See [Configuration](./configuration.md#application-configuration).

4. For each affected user, call `restart_full_sync` via the MCP tool interface. This resets sync state in the local database and re-fetches all emails from Microsoft Graph, sending them directly to the Unique KB API — bypassing RabbitMQ entirely.

5. Monitor recovery progress with `sync_progress`. The sync is complete when `fullSyncState` transitions to `"ready"` and `state` is `"finished"`.

6. Live catch-up resumes automatically once the service reconnects to RabbitMQ. Any emails received during the outage window that were not captured by webhook notifications will be picked up by `restart_full_sync` in step 4.

**See also:** [`restart_full_sync`](../technical/tools.md#restart_full_sync), [`sync_progress`](../technical/tools.md#sync_progress), [Configuration](./configuration.md#application-configuration)

---

## Scenario 3: Unique Knowledge Base Loss

### Symptoms

- `search_emails` returns no results or errors for all users.
- `sync_progress` shows `ingestionStats.failed` increasing, or `ingestionStats` returns `{ state: "error" }`.
- Service logs show errors contacting the Unique ingestion or scope management services.

### Impact

The Unique Knowledge Base stores the actual ingested email content used for semantic search. Total loss means:

- All previously ingested emails are gone — `search_emails` returns no results.
- The local database and its sync state are **not** affected.
- Microsoft Graph webhook subscriptions are **not** affected — live notifications continue to arrive.
- No re-authentication is required.

### Recovery Steps

1. Restore or verify the Unique Knowledge Base is operational and reachable from the service. Confirm `UNIQUE_INGESTION_SERVICE_BASE_URL` and `UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL` are correct in the Helm values.

2. Enable debug mode on the deployment if it is not already enabled, by setting `MCP_DEBUG_MODE=enabled` in `mcpConfig.app.mcpDebugMode`. This exposes the `restart_full_sync` tool. See [Configuration](./configuration.md#application-configuration).

3. For each affected user, call `restart_full_sync` via the MCP tool interface. This resets sync state in the local database and re-fetches all emails from Microsoft Graph, re-ingesting them into the restored Unique Knowledge Base. Re-ingestion is idempotent — file keys prevent duplicates.

4. Monitor recovery progress with `sync_progress`. The sync is complete when `fullSyncState` transitions to `"ready"` and `state` is `"finished"`.

5. Live catch-up resumes automatically once ingestion is healthy — emails received during the outage will be processed through the normal webhook pipeline without additional operator action.

**See also:** [`restart_full_sync`](../technical/tools.md#restart_full_sync), [`sync_progress`](../technical/tools.md#sync_progress), [Configuration](./configuration.md#application-configuration)
