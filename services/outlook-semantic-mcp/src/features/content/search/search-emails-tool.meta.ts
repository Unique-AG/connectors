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

  ## Combining search + conditions + limit
  The \`search\` field and the \`conditions\` array work together — always try to use both:
  - \`search\`: natural-language relevance query (e.g. "budget report from Alice").
  - \`conditions\`: structured filters (sender, date range, folder, attachments, etc.) applied on top of the semantic search.
  - \`limit\`: increase toward 300 when the query is fuzzy or broad, or when you expect a large result set.

  ## Strategy for broad or unfocused queries
  If the user's question is too broad for semantic search to be meaningful on its own (e.g. "show me all emails from last week", "list everything from alice@example.com"):
  1. Keep a broad or descriptive \`search\` term, OR use the most relevant keyword you can derive.
  2. Add precise \`conditions\` (e.g. dateFrom/dateTo, fromSenders) to narrow the candidate set.
  3. Set \`limit\` to 300 to capture as many matching emails as possible.
  This combination is more reliable than relying on semantic relevance alone for listing or enumeration tasks.

  ## Complementing semantic search with KQL (msGraphKeywordSearchQueries)
  Always fill \`msGraphKeywordSearchQueries\` alongside \`uniqueSemanticSearchQueries\` unless the query is scoped to a delegated mailbox (KQL only works on the user's own mailbox).

  The two backends cover different ground and their results are merged — semantic results are ranked first, then enriched with the KQL body excerpt when the same email was matched by both:
  - **Semantic** excels at: conceptual relevance, synonyms, natural-language intent, content inside attachments.
  - **KQL** excels at: exact keyword matches, precise property filters, full body text excerpts.

  **How to translate a semantic query into complementary KQL:**
  1. Extract the most specific keywords from the semantic query and express them as \`subject:\` and/or \`body:\` filters.
  2. Mirror any structured conditions as KQL property filters (e.g. \`fromSenders\` → \`from:\`, date range → \`received>=\`/\`received<=\`, attachments → \`hasAttachment:true\`).
  3. Run multiple KQL queries in parallel for different angles: synonyms, subject-focus vs. body-focus, alternative keyword combinations.

  Example — user asks "Q2 budget report from Alice":
  - Semantic: \`search: "Q2 budget report"\`, condition \`fromSenders: { value: "alice@example.com", operator: "equals" }\`
  - KQL query 1: \`from:alice@example.com subject:"Q2 budget"\`
  - KQL query 2: \`from:alice@example.com body:"budget report" received>=2024-04-01 received<=2024-06-30\`

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
