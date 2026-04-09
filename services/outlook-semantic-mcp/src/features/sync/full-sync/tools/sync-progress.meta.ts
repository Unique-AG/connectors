import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current sync status: whether historical email scan and live sync are active, how many emails are available in search vs. still being indexed, and what filters are applied.',
  toolFormatInformation: `## Sync Progress Display Rules

  Open with a status line, then answer the two questions the user cares about: is historical sync still running, and is live sync active. Then show search availability and active filters. Omit any field that is \`null\`.

  **Status line** — based on top-level \`state\`:
  - \`finished\` → ✅ **Sync complete**
  - \`running\` → 🔄 **Sync in progress**
  - \`error\` → ❌ **Sync error**

  If \`message\` is present and non-empty, show it as a blockquote below the status line.

  **Historical email sync** — Is Outlook scanning old emails from your history? (\`syncStats.fullSyncState\`)
  - \`running\` or \`waiting-for-ingestion\` → 🔄 Scanning email history{syncStats.expectedTotal ? \` — {syncStats.expectedTotal} emails expected in total\` : ''}
  - \`ready\` → ✅ Historical scan complete
  - \`paused\` → ⏸ Historical scan paused
  - \`failed\` → ❌ Historical scan failed

  **Live sync** — Are new emails synchronizing? (\`syncStats.liveCatchUpState\`)
  - \`running\` → 🔄 Live sync active — new emails are being picked up
  - \`ready\` → ✅ Live sync up to date
  - \`failed\` → ❌ Live sync failed

  **Email search availability** — How many emails can you search right now?
  If \`ingestionStats.state\` is \`error\`: ❌ _Search index unavailable: {ingestionStats.message}_
  Otherwise:
  - ✅ Available in search: {ingestionStats.finished}
  - ⏳ Still being indexed: {ingestionStats.inProgress} — if inProgress is 0 but the top-level \`state\` is \`running\`, show: (waiting for more emails to be uploaded); otherwise show: (will appear in search once done)
  - ❌ Failed to index: {ingestionStats.failed} (omit line if 0)
  If \`ingestionStats.failed\` > 0, append: ⚠️ _{ingestionStats.failed} email(s) could not be indexed and won't appear in search._
  Note: emails are indexed from newest to oldest, so recent emails become searchable first.

  **Emails scheduled for indexing** — Received between {syncStats.dateWindow.oldestReceivedEmailDateTime} and {syncStats.dateWindow.newestReceivedEmailDateTime}. Most recently modified: {syncStats.dateWindow.newestLastModifiedDateTime}. Omit any date that is null.

  ### Active filters
  Always show this section so the user understands which emails will be synchronized for search.

  **Ignoring emails before:** {ignoredBefore formatted as "Mon DD, YYYY"}, or _none_ if null.
  Emails with a received date before this date are permanently excluded from search — they will never appear in results.

  **Ignored senders** — each entry is a JavaScript regex in \`/pattern/flags\` format matched against the sender's email address. Emails from matching senders are excluded.
  If the list is empty, show: _No sender filters active — all senders are included._
  Otherwise list each pattern and give a plain-English explanation of what it matches, e.g.:
  - \`/noreply@.*/i\` — excludes any sender whose address contains "noreply@" (case-insensitive)
  - \`/@newsletter\\.example\\.com$/i\` — excludes senders from the domain "newsletter.example.com"

  **Ignored contents** — each entry is a JavaScript regex matched against the email subject and body. Emails where either field matches are excluded.
  If the list is empty, show: _No content filters active — all content is included._
  Otherwise list each pattern with a plain-English explanation, e.g.:
  - \`/unsubscribe/i\` — excludes emails whose subject or body contains the word "unsubscribe"
  - \`/^\\[JIRA\\]/\` — excludes emails whose subject starts with "[JIRA]"
  `,
});
