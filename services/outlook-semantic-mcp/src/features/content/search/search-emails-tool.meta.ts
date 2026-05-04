import { createMeta } from '@unique-ag/mcp-server-module';

const TOOL_FORMAT_INFORMATION = `## Email Display Rules
  ALWAYS follow these rules when displaying results from \`search_emails\` or when referencing information extracted from emails.
  ### Format for listing emails
  When listing multiple emails, use a markdown table with exactly 3 columns: Time, Sender, Subject.
  - **Time**: Use the \`receivedDateTime\` field. Format as "Mon DD, YYYY HH:MM AM/PM".
  - **Sender**: Display as "Name (email)" e.g. "Sarah Chen (sarah.chen@acme.com)".
  - **Subject**: If \`outlookWebLink\` is non-empty, link the subject to it. Otherwise display the subject as plain text.
  - Show most recent emails first.
  ### Table format
  | Time | Sender | Subject |
  |------|--------|---------|
  | {Date} | {Name (email)} | [📩 {Subject}]({outlookWebLink}) |
  ### Format when extracting or summarizing information from emails
  When the user asks a question and you answer using information found in emails (e.g. "What did Sarah say about the budget?", "When is the maintenance window?", "Summarize my conversation with Marco"), you MUST:
  - Write your answer in natural language.
  - If \`outlookWebLink\` is non-empty, include an inline link for every source email you referenced.
  - Use this format for inline references: [open email]({outlookWebLink})
  Example — user asks "What did Marco say about the partnership agreement?":
  Marco suggested a few changes to Section 3 of the partnership agreement, specifically around the liability clause and payment terms. He asked to schedule a call to discuss before signing. [open email](https://outlook.office.com/owa/?ItemID=AAkALgAA...&exvsurl=1&viewmodel=ReadMessageItem)
  Example — user asks "Summarize my recent emails with the DevOps team":
  You have 2 recent emails from DevOps:
  1. **Server maintenance** is scheduled for March 12 from 2:00–5:00 AM UTC on the production cluster. [open email](https://outlook.office.com/owa/?ItemID=AAkALgAA...&exvsurl=1&viewmodel=ReadMessageItem)
  2. **Deployment pipeline** was updated — the new CI/CD config requires all teams to re-trigger their staging builds. [open email](https://outlook.office.com/owa/?ItemID=AAkALgBB...&exvsurl=1&viewmodel=ReadMessageItem)
  ### Link rules (apply to ALL formats above)
  - NEVER show raw IDs (msGraphMessageId, uniqueContentId, folderId) to the user.
  ### Full listing example
  | Time | Sender | Subject |
  |------|--------|---------|
  | Mar 8, 2026 2:15 PM | Sarah Chen (sarah.chen@acme.com) | [📩 Q2 Budget Approval Needed](https://outlook.office.com/owa/?ItemID=AAkALgAA...&exvsurl=1&viewmodel=ReadMessageItem) |
  | Mar 7, 2026 11:42 AM | Marco Rossi (marco.rossi@external-partner.io) | [📩 Re: Partnership Agreement Draft](https://outlook.office.com/owa/?ItemID=AAkALgBB...&exvsurl=1&viewmodel=ReadMessageItem) |
  | Mar 6, 2026 9:00 AM | HR Team (hr@acme.com) | [📩 Onboarding Schedule - New Hires March 2026](https://outlook.office.com/owa/?ItemID=AAkALgCC...&exvsurl=1&viewmodel=ReadMessageItem) |
  | Mar 5, 2026 4:30 PM | Priya Patel (priya.patel@acme.com) | [📩 Accepted: Product Roadmap Review](https://outlook.office.com/owa/?ItemID=AAkALgDD...&exvsurl=1&viewmodel=ReadMessageItem) |
  | Mar 4, 2026 8:00 AM | DevOps (devops-alerts@acme.com) | [📩 Server Maintenance Window - March 12](https://outlook.office.com/owa/?ItemID=AAkALgEE...&exvsurl=1&viewmodel=ReadMessageItem) |
`;

export const META_UNIQUE_AND_MS_GRAPH = createMeta({
  icon: 'search',
  systemPrompt: `Searches ingested Outlook emails semantically. Use conditions to filter by sender, date, recipient, folder, attachments, or category. Returns matched passages from emails with metadata.

  By default search across ALL folders. Do not restrict to a specific folder unless the user asks.
  After returning results, inform the user that they can narrow the search to a specific folder if needed.

  To filter by folder, pass its name directly to the \`directories\` parameter — no need to call \`list_folders\` for well-known folders.
  Use these exact names: "Inbox", "Sent Items", "Drafts", "Archive", "Outbox", "Clutter", "Conversation History".
  Note: "Deleted Items", "Junk Email", and "Recoverable Items Deletions" are not synchronized — searching through them will not return results.
  For custom user-defined folders, call \`list_folders\` first to get the folder ID.

  If the response includes a "syncWarning", display it to the user before showing results so they understand results may be incomplete.`,
  toolFormatInformation: TOOL_FORMAT_INFORMATION,
});

export const META_MS_GRAPH = createMeta({
  icon: 'search',
  systemPrompt: `Searches Outlook emails using Microsoft Graph KQL queries. Returns matched emails with metadata.

  By default search across ALL folders. Do not restrict to a specific folder unless the user asks.
  After returning results, inform the user that they can narrow the search with more specific KQL terms if needed.

  Build precise KQL queries using supported property filters: from:, to:, cc:, subject:, body:, received>=, received<=, hasAttachment:, category:.
  Combine clauses with AND/OR for complex searches. You can run multiple KQL queries in parallel (up to 20) for broader coverage.`,
  toolFormatInformation: TOOL_FORMAT_INFORMATION,
});
