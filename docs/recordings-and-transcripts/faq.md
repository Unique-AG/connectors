<!-- confluence-page-id: 2535129116 -->
<!-- confluence-space-key: PUBDOC -->

Questions about capturing meeting transcripts and recordings into the Unique knowledge base, and about the Recordings area that presents them. For questions about the Teams MCP Server itself — OAuth, consent, tokens, chat and channel tools — see the [Teams MCP - FAQ](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1801846803/Teams+MCP+-+FAQ).

## Eligibility & Scope

### Do I have to store recordings in Unique to use Teams MCP?

**Answer:** No. The Teams MCP Server runs in chat-only mode by default (`UNIQUE_INTEGRATION=disabled`), where it ingests nothing at all: Teams chat and channel messages are fetched live from Microsoft Graph on every call and no copy is kept in Unique. Recordings & Transcripts is a separate, opt-in capability that requires `UNIQUE_INTEGRATION=enabled`.

If your organisation cannot store meeting content in Unique, deploy Teams MCP in chat-only mode and ignore this section of the documentation.

### What exactly is stored in Unique?

**Answer:** For every captured meeting: the transcript as a WebVTT file, the video recording as an MP4 file when the meeting was recorded, and any reports the platform generates from the transcript. The transcript is fully indexed and searchable by Unique AI. The recording is stored for playback only — it is not transcribed or indexed again.

**See also:** [What is stored](./README.md#what-is-stored)

### Are Teams chat and channel messages ingested as well?

**Answer:** No. Only meeting transcripts and recordings are copied into Unique. Chat and channel messages are always read live through Microsoft Graph and never stored in the knowledge base, regardless of whether this feature is enabled.

## Setup & Configuration

### Why do transcript Graph calls return 403 after admin consent?

**Answer:** Microsoft rejects transcript subscription create/renew and transcript fetches with **403** (`GraphAccessToTranscriptsDisabled`) when the tenant-wide Teams meeting setting **Microsoft Graph access** under Transcript API access is off. By default this setting is off, regardless of Entra app permissions.

This is **not** fixed by re-consent, reconnecting with a different app, or changing subscription IDs. Entra admin consent grants `OnlineMeetingTranscript.Read.All`; `EnableGraphTranscriptAccess` is a separate Teams control. Unique cannot enable it via OAuth or Graph.

**What to do (Teams / Global admin):**

1. Teams admin center → **Meetings → Meeting settings** → under **Transcript API access**, set **Microsoft Graph access → On**
2. Optionally enable **Include speaker attribution** (Unique expects attributed VTT)
3. Or via PowerShell:
   ```powershell
   Set-CsTeamsMeetingConfiguration -Identity Global -EnableGraphTranscriptAccess $true
   Set-CsTeamsMeetingConfiguration -Identity Global -EnableAttributedTranscripts $true
   ```
4. Wait a few minutes, then have the user call `start_kb_integration` again and confirm with `verify_kb_integration_status` → `active`

**See also:** [Teams Graph transcript API access](./operator.md#Teams-Graph-transcript-API-access) · [Meeting transcript API access (Microsoft)](https://learn.microsoft.com/en-us/microsoftteams/meeting-transcript-api-access)

### Why do I need a Zitadel service account?

**Answer:** Ingestion happens on behalf of the server rather than an end user, so the Teams MCP Server needs its own identity against the Unique Public API. It uses that identity to resolve meeting participants to Unique accounts, create the scopes that hold each meeting, grant the organiser and participants access, and upload the transcript and recording.

Credentials are passed as the `x-company-id` and `x-user-id` headers on every API request. The account must hold both `chat.admin.all` and `chat.knowledge.read`.

**See also:** [Zitadel service account](./operator.md#Zitadel-service-account)

### Why do I need a dedicated root scope?

**Answer:** Every meeting is ingested as a child scope beneath one root scope, which gives Teams content a single organisational entry point and one place to manage permissions and visibility. The Recordings area reads from exactly that scope. The root scope must be created manually and the service account must be granted `MANAGE`, `READ`, and `WRITE` on it before the server starts — otherwise the pod hard-fails at boot.

**See also:** [Root scope](./operator.md#Root-scope)

### Why must the two scope IDs match?

**Answer:** `UNIQUE_ROOT_SCOPE_ID` tells Teams MCP where to write; `RECORDING_KB_SCOPE_ID` tells the Recordings area where to read. If they differ, ingestion succeeds and the Recordings area stays permanently empty, with no error raised anywhere. This is the single most common misconfiguration.

**See also:** [Enable the Recordings area in Unique](./operator.md#enable-the-recordings-area-in-unique)

### What happens if the webhook secret changes?

**Answer:** **Rotation is currently not possible.** `MICROSOFT_WEBHOOK_SECRET` is sent to Microsoft as the subscription `clientState`, so every existing subscription carries the old value and will fail validation once the secret changes. There is no automated mechanism to recreate them.

If rotation becomes unavoidable, it requires deleting all subscriptions and having every user re-subscribe, which will miss any transcripts produced during the gap.

> **Note:** Automated rotation may be part of a future release.

### Can one deployment capture meetings from several Microsoft tenants?

**Answer:** Yes, with a multi-tenant app registration — but a single user session covers exactly one tenant. A user who belongs to multiple tenants must connect once per tenant, and each connection captures that tenant's meetings under the identity used to connect it.

**See also:** [Teams MCP - FAQ](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1801846803/Teams+MCP+-+FAQ)

## Data Sync

### Why can't historical transcripts be synced?

**Answer:** Microsoft Graph does not provide a way to list transcripts across all past meetings using delegated permissions. The only cross-meeting listing API is `getAllTranscripts`, which Microsoft marks as **not supported** for delegated permissions:

```
GET /users/{userId}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{userId}',startDateTime=...)
```

With delegated permissions the only available path is `GET /users/{userId}/onlineMeetings/{meetingId}/transcripts`, which requires knowing the meeting id in advance — making bulk historical enumeration impossible. Capture therefore only covers meetings that occur **after** a user enables it.

Individual past meetings can still be pulled in one at a time with `ingest_meeting`, as long as they have not expired on the Microsoft side.

**See also:** [Microsoft Graph constraints](./technical.md#no-historical-or-full-sync)

### Why is there no delta sync?

**Answer:** Microsoft Graph does expose delta APIs for transcripts and recordings, supporting both full initial sync and incremental sync, but they require **application permissions** — delegated permissions are explicitly not supported. Teams MCP uses delegated permissions so users can connect their own Microsoft account without IT involvement, so it relies on real-time change notifications instead. These cover everything going forward but cannot recover anything missed during a subscription gap.

**See also:** [Microsoft Graph constraints](./technical.md#no-delta-sync)

### What happens if transcripts are missed during a subscription gap?

**Answer:** They are permanently lost as far as automatic capture is concerned. Microsoft Graph only delivers notifications for transcripts created while a subscription is active, and there is no catch-up or replay mechanism.

To minimise the risk:

- Monitor for `subscription_renewal_failed` log events — a failed renewal is the most common cause of a gap
- Keep users connected; an expired Microsoft token breaks renewal
- Recover individual meetings with `ingest_meeting`

**See also:** [Subscription failure handling](./technical.md#subscription-failure-handling)

## Subscriptions & Processing

### Why do subscriptions expire?

**Answer:** Microsoft Graph subscriptions expire after a maximum of three days. The server renews them automatically ahead of expiry, batching renewals into a configured off-peak UTC hour (default: 3 AM) so that token validity is checked on a predictable schedule.

**See also:** [Subscription lifecycle](./technical.md#subscription-lifecycle)

### Why are subscriptions renewed instead of recreated?

**Answer:** Recreation loses transcripts. Microsoft Graph only sends notifications for transcripts created while a subscription is active, so the window between a `DELETE` and the following `POST` is a permanent hole — anything produced in it never generates a notification. Renewal (`PATCH`) keeps the subscription continuously active, preserves the subscription id, and costs fewer API calls.

**See also:** [Renewal](./technical.md#renewal)

### What happens if a subscription renewal fails?

**Answer:** The subscription is deleted and the user must reconnect and call `start_kb_integration` again. Common causes are an expired Microsoft refresh token (roughly 90 days of inactivity), revoked consent, network problems reaching Microsoft, or tenant Graph transcript API access being disabled (`EnableGraphTranscriptAccess` off) — renewals return 403 and re-consent will not help (see [Why do transcript Graph calls return 403 after admin consent?](#why-do-transcript-graph-calls-return-403-after-admin-consent)). Transcripts produced between the failed renewal and re-subscription are lost.

**See also:** [Subscription failure handling](./technical.md#subscription-failure-handling)

### Why aren't transcripts appearing in Unique?

**Answer:** Work through the chain in order:

1. **Is Graph transcript API access on?** Confirm `EnableGraphTranscriptAccess` — see [403 after admin consent](#why-do-transcript-graph-calls-return-403-after-admin-consent)
2. **Is capture enabled for that user?** `verify_kb_integration_status` should report `active`
3. **Was the meeting transcribed?** Only meetings with transcription enabled produce anything to capture
4. **Are notifications arriving?** Check that Microsoft can reach the public webhook URL
5. **Is the queue draining?** Check RabbitMQ, including the dead-letter queue
6. **Did ingestion fail?** Check the server logs for errors during participant resolution or upload
7. **Are you looking at the right scope?** Content lands under `UNIQUE_ROOT_SCOPE_ID`

**See also:** [Troubleshooting](./operator.md#troubleshooting)

### Why use RabbitMQ for webhook processing?

**Answer:** Microsoft requires webhook endpoints to respond within **10 seconds** or it treats the delivery as failed and retries. Processing a transcript notification involves database lookups, several Microsoft Graph calls, participant resolution, and content upload, which routinely takes 30 seconds or more.

RabbitMQ decouples reception from processing: the webhook controller validates the notification, publishes it, and returns `202 Accepted` immediately, while a consumer performs the slow work asynchronously. This also provides durability, a dead-letter exchange for failed messages, horizontal scaling, and burst absorption.

### Can I enable this feature without RabbitMQ?

**Answer:** No. RabbitMQ is required to meet Microsoft's webhook response time limit. Without it, webhook processing would time out and Microsoft would eventually stop sending notifications. (A chat-only Teams MCP deployment does not need RabbitMQ, because it has no webhook pipeline.)

### What happens to messages that fail processing?

**Answer:** They are nacked and routed to a Dead Letter Exchange, where they accumulate indefinitely — there is no automatic TTL or retry. An operator must inspect the dead-letter queue (for example via the RabbitMQ management UI) and decide whether to republish or discard each message. Because no delta sync exists, a message in the DLQ is the only copy of that notification: discarding it means the transcript is never ingested.

## The Recordings Area

### Who can see a meeting in the Recordings area?

**Answer:** Only users who were granted access when the meeting was ingested, plus anyone it was shared with afterwards. The organiser gets read and write access, participants get read access, and both are resolved to Unique accounts by email or username. The Recordings area applies normal knowledge-base access control on every read, so users never see meetings they were not granted.

### Why do some participants have no access to a meeting they attended?

**Answer:** Either they do not resolve to a Unique account — external guests, for instance — or their Zitadel account lacks the roles Unique requires for the access being granted. The meeting is still captured; those participants simply do not receive access, and someone with access can share it with them afterwards.

**See also:** [Required roles](./operator.md#required-roles)

### Why does a meeting have a transcript but no video?

**Answer:** Most often because the meeting was transcribed but never recorded — transcription and recording are independent in Teams. It can also happen when the recording download timed out, which is a real risk for very long meetings since there is no application-level size limit. Recording failures never block transcript capture, so a transcript-only entry is the expected outcome.

### Can users delete a recording?

**Answer:** Yes, if they hold knowledge-base write or admin permission. Deleting removes the transcript, the correlated video, and the meeting's reports from the Unique knowledge base. It does not affect anything on the Microsoft side.

### What are reports, and can users generate them on demand?

**Answer:** Reports are AI-generated summaries produced by the platform's reporting engine from an ingested transcript. They appear in the recording detail view once generated, and the view offers a refresh action for reports still in progress. Triggering a new report from the Recordings area is not available today.

### The Recordings area is empty even though meetings were ingested. Why?

**Answer:** Almost always a scope mismatch: `RECORDING_KB_SCOPE_ID` must be the exact scope Teams MCP ingests into (`UNIQUE_ROOT_SCOPE_ID`). Failing that, check that the current user actually has access to any captured meeting, and that the transcript content is present under the root scope.

**See also:** [Troubleshooting](./operator.md#troubleshooting)

### What happens when a user disconnects their Microsoft account?

**Answer:** Capture stops for that user, but everything already captured **stays** in the Unique knowledge base and remains visible in the Recordings area and searchable by Unique AI. The same is true of `stop_kb_integration`: it stops future capture and deletes nothing.

## Related Documentation

- [Recordings & Transcripts](./README.md) — what the feature is and who it is for
- [Operator Manual](./operator.md) — configuration, enablement checklist, and troubleshooting
- [Technical Manual](./technical.md) — architecture, ingestion pipeline, subscription lifecycle, and tools
- [Teams MCP - FAQ](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1801846803/Teams+MCP+-+FAQ) — OAuth, consent, tokens, and the chat and channel tools

## Standard References

- [Microsoft Graph Change Notifications](https://learn.microsoft.com/en-us/graph/webhooks) - Webhook subscription model
- [callTranscript: delta](https://learn.microsoft.com/en-us/graph/api/calltranscript-delta) - Delta API permission requirements
- [onlineMeeting: getAllTranscripts](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-getalltranscripts) - Cross-meeting transcript listing
- [Limits and specifications for Microsoft Teams](https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams) - Meeting and transcript expiration
