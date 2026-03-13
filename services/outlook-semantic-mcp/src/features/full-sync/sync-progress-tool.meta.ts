import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current sync progress including inbox configuration, date windows, and ingestion statistics. Use this to monitor sync state and ingestion progress.',
  toolFormatInformation: `## Sync Progress Display Rules

  Open with a status line, then show the sync state and ingestion as compact sections. Omit any field that is \`null\`.

  **Status line** — based on top-level \`state\`:
  - \`finished\` → ✅ **Sync complete**
  - \`running\` → 🔄 **Sync in progress**
  - \`error\` → ❌ **Sync error**

  If \`message\` is present and non-empty, show it as a blockquote below the status line.

  **Sync State** — Full sync: {syncStats.fullSyncState}, Live catch-up: {syncStats.liveCatchUpState}
  - \`fullSyncState\` values: \`ready\` (initial fetch done), \`fetching-emails\` (fetch in progress), \`failed\` (error)
  - \`liveCatchUpState\` values: \`ready\` (up to date), \`running\` (processing new emails), \`failed\` (error)

  **Date Window** — Newest created: {syncStats.dateWindow.newestCreatedDateTime}, Oldest created: {syncStats.dateWindow.oldestCreatedDateTime}, Newest modified: {syncStats.dateWindow.newestLastModifiedDateTime}, Oldest modified: {syncStats.dateWindow.oldestLastModifiedDateTime}

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
