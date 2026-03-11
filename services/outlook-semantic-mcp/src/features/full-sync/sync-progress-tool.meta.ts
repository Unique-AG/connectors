import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current full sync progress including inbox configuration and ingestion statistics. Use this to monitor how many emails have been processed and their ingestion states.',
  toolFormatInformation: `## Sync Progress Display Rules

  Open with a status line, then show the two phases as compact sections. Omit any field that is \`null\`.

  **Status line:**
  - \`idle\` → ✅ **Sync complete**
  - \`running\` → 🔄 **Sync in progress** — {progressPercentage}%
  - \`unknown\` → ⚠️ **Sync state unknown** — inbox connection could not be found.

  If \`message\` is present, show it as a blockquote below the status line.

  **Fetch & Queue** ({toQueueForIngestionStats.state}) — received / queued / processed: {received} / {queuedForSync} / {processed}
  If state is `failed`, append: ⚠️ _Fetch & queue phase encountered an error._
  **Ingestion** ({ingestionStats.state}) — finished / in progress / failed: {finished} / {inProgress} / {failed} - Emails are ingested from newest emails received to oldest emails.
  If `failed` > 0, append: ⚠️ _{failed} email(s) failed ingestion._

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
