import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current sync progress including inbox configuration, date windows, and ingestion statistics. Use this to monitor sync state and ingestion progress.',
  toolFormatInformation: `## Sync Progress Display Rules

  Open with a status line, then show the sync state and ingestion as compact sections. Omit any field that is \`null\`.

  **Status line:**
  - \`finished\` → ✅ **Sync complete**
  - \`running\` → 🔄 **Sync in progress**
  - \`error\` → ❌ **Sync error**

  If \`message\` is present, show it as a blockquote below the status line.

  **Sync State** — Full sync: {syncStats.fullSyncState}, Live catch-up: {syncStats.liveCatchUpState}
  **Date Window** — Newest created: {newestCreatedDateTime}, Oldest created: {oldestCreatedDateTime}, Newest modified: {newestLastModifiedDateTime}, Oldest modified: {oldestLastModifiedDateTime}
  **Ingestion** ({ingestionStats.state}) — finished / in progress / failed: {finished} / {inProgress} / {failed} - Emails are ingested from newest emails received to oldest emails.
  If \`failed\` > 0, append: ⚠️ _{failed} email(s) failed ingestion._

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
