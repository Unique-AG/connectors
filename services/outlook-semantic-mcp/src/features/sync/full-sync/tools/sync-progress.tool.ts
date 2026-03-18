import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetFullSyncStatsQuery, GetFullSyncStatsResponse } from '../get-full-sync-stats.query';

const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current sync progress including inbox configuration, date windows, counters (expectedTotal, skippedMessages, scheduledForIngestion, failedToUploadForIngestion), and ingestion statistics. Use this to monitor sync state and ingestion progress.',
  toolFormatInformation: `## Sync Progress Display Rules

  Open with a status line, then show the sync state and ingestion as compact sections. Omit any field that is \`null\`.

  **Status line** — based on top-level \`state\`:
  - \`finished\` → ✅ **Sync complete**
  - \`running\` → 🔄 **Sync in progress**
  - \`error\` → ❌ **Sync error**

  If \`message\` is present and non-empty, show it as a blockquote below the status line.

  **Sync State** — Full sync: {syncStats.fullSyncState}, Live catch-up: {syncStats.liveCatchUpState}
  - \`fullSyncState\` values: \`ready\` (initial fetch done), \`running\` (in progress), \`failed\` (error), \`paused\` (user paused), \`waiting-for-ingestion\` (draining ingestion queue)
  - \`liveCatchUpState\` values: \`ready\` (up to date), \`running\` (processing new emails), \`failed\` (error)

  **Counters** — show as a compact table or list:
  - Expected total: {syncStats.expectedTotal} (omit if null — count was unavailable)
  - Skipped: {syncStats.skippedMessages} (filtered out by rules)
  - Scheduled for ingestion: {syncStats.scheduledForIngestion} (uploaded successfully)
  - Failed to upload: {syncStats.failedToUploadForIngestion} (failed after retries)

  **Date Window** — Newest created: {syncStats.dateWindow.newestCreatedDateTime}, Newest modified: {syncStats.dateWindow.newestLastModifiedDateTime}

  **Ingestion** — if \`ingestionStats.state\` is \`error\`, show: ❌ _Ingestion unavailable: {ingestionStats.message}_
  Otherwise (\`ingestionStats.state\` is \`finished\` or \`running\`):
  ({ingestionStats.state}) — finished / in progress / failed: {ingestionStats.finished} / {ingestionStats.inProgress} / {ingestionStats.failed} — Emails are ingested from newest to oldest.
  If \`ingestionStats.failed\` > 0, append: ⚠️ _{ingestionStats.failed} email(s) failed ingestion._

  ### Active filters
  Always show the active filters section so the user understands what is being ingested.

  **Ignoring emails before:** {ignoredBefore formatted as "Mon DD, YYYY"}, or _none_ if null.
  Emails received before this date are never ingested — they are permanently excluded from search.

  **Ignored senders** — each entry is a JavaScript regex in \`/pattern/flags\` format matched against the sender's email address. Emails from matching senders are excluded from ingestion.
  If the list is empty, show: _No sender filters active — all senders are ingested._
  Otherwise list each pattern and give a plain-English explanation of what it matches, e.g.:
  - \`/noreply@.*/i\` — excludes any sender whose address contains "noreply@" (case-insensitive)
  - \`/@newsletter\\.example\\.com$/i\` — excludes senders from the domain "newsletter.example.com"

  **Ignored contents** — each entry is a JavaScript regex matched against the email subject and body. Emails where either field matches are excluded from ingestion.
  If the list is empty, show: _No content filters active — all content is ingested._
  Otherwise list each pattern with a plain-English explanation, e.g.:
  - \`/unsubscribe/i\` — excludes emails whose subject or body contains the word "unsubscribe"
  - \`/^\\[JIRA\\]/\` — excludes emails whose subject starts with "[JIRA]"
  `,
});

const InputSchema = z.object({});

const OutputSchema = GetFullSyncStatsResponse;

@Injectable()
export class SyncProgressTool {
  public constructor(private readonly getFullSyncStatsQuery: GetFullSyncStatsQuery) {}

  @Tool({
    name: 'sync_progress',
    title: 'Sync Progress',
    description:
      'Check the current progress of the full email sync. Returns inbox configuration details and ingestion statistics. Use after `run_full_sync` to monitor progress, or when `search_emails` returns a `syncWarning`.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Sync Progress',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async fullSyncProgress(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    return await this.getFullSyncStatsQuery.run(userProfileTypeid);
  }
}
