<!-- confluence-page-id:  -->
<!-- confluence-space-key: PUBDOC -->

# Disaster Recovery

This runbook covers recovery procedures for the three stateful components the Outlook Semantic MCP Server depends on: the local PostgreSQL database, RabbitMQ, and the Unique Knowledge Base. Each component has a distinct failure mode and recovery path.

Automatic recovery schedulers (a 2-minute full-sync retry and a 5-minute live catch-up) handle transient failures. The scenarios below require explicit operator action because the automatic schedulers are insufficient for total data loss.

Out of scope: partial database corruption, Microsoft Graph API outages, and automated recovery scripts.

---

## Recovery Considerations

### Idempotent re-ingestion

For all recovery scenarios except Knowledge Base loss (Scenario 3), the system checks whether each email already exists in the Knowledge Base before re-ingesting it. If the file key matches and the metadata is unchanged, the email is skipped entirely. The only cost of a full re-sync in these cases is:

- **Microsoft Graph API calls** to re-fetch email metadata (pages of 100 messages).
- **Ingestion API lookups** to check whether each file key already exists.

No duplicate content is written to the Knowledge Base. This means that even a full re-sync after database or RabbitMQ loss is a lightweight operation relative to the initial sync — the overhead is API calls, not data re-processing.

In Scenario 3 (Knowledge Base loss), the content must be fully re-ingested because the Knowledge Base no longer contains the files. This is the only scenario where re-sync carries the full cost of initial ingestion.

### Recovery time factors

The documentation does not provide fixed RTO targets because recovery time varies significantly by deployment. The main factors are:

- **Number of connected users** — each user's mailbox is re-synced independently. The service processes users concurrently but enforces a batch limit of 50 messages per cycle per user before yielding to others (hardcoded service limit).
- **Mailbox size** — full sync fetches emails in pages of 100 from Microsoft Graph (service-configured page size), processing them sequentially. Large mailboxes (100,000+ emails) take proportionally longer.
- **Microsoft Graph API rate limits** — Microsoft enforces a global limit of 130,000 requests per 10 seconds per app across all tenants; additional per-mailbox and per-service limits may apply (Microsoft limit, not configurable). Re-syncing many users simultaneously may approach these limits. There is no built-in staggering; operators may need to trigger `restart_full_sync` for users in batches to avoid throttling. See [Microsoft Graph throttling](https://learn.microsoft.com/en-us/graph/throttling).
- **Ingestion concurrency** — the RabbitMQ consumer prefetch count is set to 10, limiting in-flight messages per consumer (hardcoded service limit).
- **Infrastructure provisioning** — if PostgreSQL or RabbitMQ must be provisioned from scratch rather than restored from backup, lead time depends on the platform. Clients using managed database services rather than Kubernetes-native solutions (e.g. CNPG) should account for provider-specific provisioning and configuration time.

### Backup recommendations

| Component | Recommendation | Rationale |
|---|---|---|
| **PostgreSQL** | Regular backups strongly recommended. Use your platform's backup solution (managed service snapshots, `pg_dump`, or WAL archiving). | Contains OAuth tokens, webhook subscriptions, and all sync state. Without a backup, all users must re-authenticate and full sync restarts from scratch. |
| **RabbitMQ** | Backup not required. | Queues are durable but carry only transient sync trigger events. The 2-minute full-sync recovery scheduler and 15-minute live catch-up cron re-create any lost events after reconnection. |
| **Unique Knowledge Base** | Managed by the Unique platform. | Backup and restore are the responsibility of the Unique platform operator. |

**Risk if no PostgreSQL backup exists:** every user must re-authenticate via OAuth and a full re-sync runs for each user. Existing emails in the Knowledge Base are not lost (re-ingestion is idempotent — only API call overhead, no duplicate data), but recovery time scales linearly with user count and mailbox size. For large deployments this can be significant, compounded by the shared Microsoft Graph API rate limit.

### Data loss window

Emails are sourced from Microsoft Graph, which retains the authoritative copy. In all three disaster scenarios, email content is not permanently lost — it can be re-fetched and re-ingested. The data loss window refers to the delay before the system catches up:

- **Webhook notifications lost during an outage** are recovered by the 15-minute live catch-up cron, which polls Microsoft Graph for any emails modified since the last known watermark.
- **If a webhook subscription expires during an extended outage** (subscriptions renew daily), the operator or user must call `reconnect_inbox` to re-create it. Emails received during the gap are picked up by the subsequent full re-sync.
- **Worst case:** emails received between the last successful live catch-up and service restoration are delayed, not lost. Full re-sync recovers all historical email from Microsoft Graph.

### Personnel

| Role | When needed |
|---|---|
| **Kubernetes operator** | All scenarios — restarts pods, updates secrets, runs migrations, enables debug mode. |
| **Database / platform administrator** | Scenario 1 — restores or provisions PostgreSQL. Scenario 2 — restores or provisions RabbitMQ. |
| **End users** | Scenario 1 only — must call `reconnect_inbox` to re-authenticate. Not needed for Scenarios 2 or 3. |

No Microsoft tenant administrator action is required for recovery. Orphaned webhook subscriptions in Microsoft's systems expire automatically based on the expiration time set at creation (the service configures subscriptions to renew daily, so orphaned subscriptions typically expire within about 1 day; Microsoft allows up to 7 days for message subscriptions).

---

## Scenario 1: Local PostgreSQL Database Loss

### Symptoms

- Service fails to start with database connection errors in the logs.
- All MCP tools return errors or empty responses.
- No users appear connected — `verify_inbox_connection` returns `not_configured` for all users.

### Impact

The local database stores OAuth tokens, Microsoft Graph webhook subscriptions, and all sync state. Total loss of the database means:

- All users must re-authenticate via the OAuth flow.
- All Graph webhook subscriptions are orphaned in Microsoft's systems (they expire naturally based on their expiration time — typically within about 1 day given the service's daily renewal cycle; Microsoft allows up to 7 days for message subscriptions).
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

2. Trigger a deploy or restart the service pods. Database migrations run automatically via the Helm hook on deploy — there is no need to run them manually via `kubectl exec` (the pods may not be running if the DB was lost):

   ```bash
   kubectl rollout restart deploy/outlook-semantic-mcp -n outlook-semantic-mcp
   ```

3. Verify migrations ran successfully by checking the pod logs:

   ```bash
   kubectl logs deploy/outlook-semantic-mcp -n outlook-semantic-mcp | grep -i migration
   ```

4. Notify affected users that they must reconnect their inbox. Each user must:

   - Open the MCP tool interface.
   - Call `reconnect_inbox` (or follow the standard OAuth flow) to re-authenticate and re-create the Graph webhook subscription.

5. After reconnection, a full sync starts automatically. Monitor progress per user with `sync_progress`.

6. Previously ingested emails remain in the Unique Knowledge Base and are unaffected. The post-recovery full sync checks each email against the Knowledge Base by file key and skips any that already exist — the only overhead is Microsoft Graph API calls and ingestion API lookups, not actual re-ingestion (see [Idempotent re-ingestion](#idempotent-re-ingestion)).

**See also:** [Authentication](./authentication.md), [Deployment](./deployment.md#database-migration), [Security — Encryption](../technical/security.md#microsoft-tokens-encrypted-at-rest)

---

## Scenario 2: RabbitMQ Loss

### Symptoms

- Service logs show AMQP connection errors or failed message publish attempts.
- In-progress full syncs complete their current batch but no new batches are triggered — `sync_progress` shows `fullSyncState: "running"` but `scheduledForIngestion` stops incrementing after the current batch finishes.
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

3. Enable debug mode on the deployment if it is not already enabled, by setting `MCP_DEBUG_MODE=enabled` in `mcpConfig.app.mcpDebugMode` and restarting pods. This exposes debug tools including `restart_full_sync`, `run_full_sync`, `pause_full_sync`, and `resume_full_sync`. **Note:** Debug mode exposes these tools to all connected MCP users, not just operators — restrict MCP client access during recovery. See [Configuration](./configuration.md#application-configuration).

4. Notify affected users that they must call `restart_full_sync` from their own MCP session. All MCP tools are scoped to the authenticated user — there is no way for an operator to trigger this on behalf of users. For large deployments, see [Bulk Recovery](#bulk-recovery). This resets sync state in the local database and triggers a re-fetch of all emails from Microsoft Graph via the restored RabbitMQ pipeline. Emails already in the Knowledge Base are detected by file key and skipped — the only overhead is Microsoft Graph API calls and ingestion API lookups (see [Idempotent re-ingestion](#idempotent-re-ingestion)).

5. Each user can monitor their own recovery progress with `sync_progress`. The sync is complete when `fullSyncState` transitions to `"ready"` and `state` is `"finished"`.

6. Live catch-up resumes automatically once the service reconnects to RabbitMQ. Any emails received during the outage window that were not captured by webhook notifications will be picked up by `restart_full_sync` in step 4.

7. Once all users show `fullSyncState: "ready"`, disable debug mode by removing or unsetting `MCP_DEBUG_MODE` in the Helm values and redeploying (requires a pod restart). Debug mode should not remain enabled in production.

**See also:** [`restart_full_sync`](../technical/tools.md#restart_full_sync), [`sync_progress`](../technical/tools.md#sync_progress), [Configuration](./configuration.md#application-configuration)

---

## Bulk Recovery

All MCP tools — including `restart_full_sync` and `sync_progress` — are scoped to the authenticated user's session. There is no admin API or batch endpoint to trigger recovery across multiple users at once. Each user must call `restart_full_sync` from their own MCP session.

For deployments with many connected users:

1. **Enable debug mode** — set `MCP_DEBUG_MODE=enabled` in the Helm values and redeploy.

2. **Notify affected users** — instruct each user to call `restart_full_sync` from their MCP client. There is no way for an operator to trigger this on behalf of users.

3. **Monitor progress** — each user can check their own recovery status with `sync_progress`. Operators can monitor service-level health via logs and metrics.

4. **Disable debug mode** — once recovery is complete, remove `MCP_DEBUG_MODE` and redeploy.

!!! warning "Debug Mode Security"
    Enabling `MCP_DEBUG_MODE=enabled` exposes debug tools (`restart_full_sync`, `run_full_sync`, `pause_full_sync`, `resume_full_sync`) to **all connected MCP users**, not just operators. There is currently no way to expose debug tools to operators only — the flag is global. **Mitigation:** restrict MCP client access during the recovery window (e.g., via network policies or ingress rules that limit which clients can reach the server). Enabling and disabling debug mode requires a Helm values change and a pod restart (`kubectl rollout restart`). For large deployments, the recovery window may last hours or days depending on user count and mailbox size — plan accordingly.

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

2. Enable debug mode on the deployment if it is not already enabled, by setting `MCP_DEBUG_MODE=enabled` in `mcpConfig.app.mcpDebugMode` and restarting pods. This exposes debug tools including `restart_full_sync`, `run_full_sync`, `pause_full_sync`, and `resume_full_sync`. **Note:** Debug mode exposes these tools to all connected MCP users, not just operators — restrict MCP client access during recovery. See [Configuration](./configuration.md#application-configuration).

3. Notify affected users that they must call `restart_full_sync` from their own MCP session. All MCP tools are scoped to the authenticated user — there is no way for an operator to trigger this on behalf of users. For large deployments, see [Bulk Recovery](#bulk-recovery). This resets sync state in the local database and re-fetches all emails from Microsoft Graph, re-ingesting them into the restored Knowledge Base. Unlike Scenarios 1 and 2, this is the only recovery scenario where emails must be fully re-ingested — the Knowledge Base no longer contains the files, so the cost includes Microsoft Graph API calls, ingestion API calls, and the full content transfer. Subsequent runs are idempotent — file keys prevent duplicates.

4. Each user can monitor their own recovery progress with `sync_progress`. The sync is complete when `fullSyncState` transitions to `"ready"` and `state` is `"finished"`.

5. Live catch-up resumes automatically once ingestion is healthy — emails received during the outage will be processed through the normal webhook pipeline without additional operator action.

6. Once all users show `fullSyncState: "ready"`, disable debug mode by removing or unsetting `MCP_DEBUG_MODE` in the Helm values and redeploying (requires a pod restart). Debug mode should not remain enabled in production.

**See also:** [`restart_full_sync`](../technical/tools.md#restart_full_sync), [`sync_progress`](../technical/tools.md#sync_progress), [Configuration](./configuration.md#application-configuration)
