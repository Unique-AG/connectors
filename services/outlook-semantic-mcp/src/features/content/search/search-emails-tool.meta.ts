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
  - NEVER construct or guess email URLs. When \`outlookWebLink\` is empty, show the subject as plain text only.
  ### searchNotes
  If the response includes a \`searchNotes\` field, display it to the user after the results — it contains context about the search run (e.g. folders excluded, mailboxes unavailable).
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

  ## Step 1 — Reason about structured filters in the user's question (do this FIRST)
  Before drafting any queries, read the user's question and try to identify signals that map cleanly to a structured filter:
  - Specific sender, sender name, or sender domain (e.g. "from Alice", "emails from @acme.com") → \`fromSenders\`
  - Specific recipient or recipient domain ("to Bob", "to anyone @client.com") → \`toRecipients\` / \`ccRecipients\`
  - Date range or relative time ("last week", "since March", "in Q2 2024") → \`dateFrom\` / \`dateTo\`
  - Attachment requirement ("with attachments", "PDFs from Alice") → \`hasAttachments\`
  - Folder mention ("in my Inbox", "from Sent Items") → \`directories\`
  - Category label ("tagged Important") → \`categories\`
  - Company name, ticker, or person name that may appear **anywhere** in the email body (e.g. "emails mentioning UBS", "where Zach Greenwald is mentioned") → no structured filter applies here; rely on semantic \`search\` AND always add a KQL \`body:\` entry for exact-match recall (e.g. \`body:UBS\`, \`body:"Zach Greenwald"\`). Use \`participants:\` in KQL when the name may appear in any address field.

  When you are confident a signal maps to one of these filters, prefer expressing it in BOTH backends:
  1. As a \`conditions\` entry on every \`uniqueSemanticSearchQueries\` entry that targets the same intent. Semantic search honors structured filters and tends to produce sharper results when conditions are populated than when the same signal is encoded only in the natural-language \`search\` text. A common failure mode is to phrase the filter in \`search\` ("emails from alice@x.com about budget") and leave \`conditions\` empty — generally avoid that.
  2. As the matching KQL property filter on every relevant \`msGraphKeywordSearchQueries\` entry (e.g. \`from:\`, \`to:\`, \`received>=\`, \`hasAttachment:true\`, \`category:\`).

  If a signal is ambiguous (e.g. an unspecific name, a vague time reference you can't confidently map to a date range), it is fine to omit the condition rather than guess wrong — but lean toward populating conditions whenever the user's intent is clear.

  ## Combining search + conditions + limit
  The \`search\` field and the \`conditions\` array work together — always try to use both:
  - \`search\`: natural-language relevance query (e.g. "budget report"). Keep it focused on the topic, not the filters — the filters belong in \`conditions\`.
  - \`conditions\`: structured filters (sender, date range, folder, attachments, etc.) applied on top of the semantic search.
  - \`limit\`: increase toward 300 when the query is fuzzy or broad, or when you expect a large result set.

  ## Multi-angle semantic search
  You can pass up to 10 entries in \`uniqueSemanticSearchQueries\` — they all run in parallel and results are merged and deduplicated.
  Use this to approach the same question from multiple angles and ensure full coverage:
  - **Different phrasings / synonyms**: e.g. "project kick-off" and "project launch" and "project start".
  - **Narrower vs. broader scope**: e.g. one entry with tight conditions (specific sender + date range) and another with no conditions but a more descriptive search term.
  - **Different condition combinations**: e.g. one entry filtering by folder "Inbox", another filtering by folder "Sent Items", to capture both sides of a conversation.
  - **Perspective shift**: e.g. "emails I sent about the merger" alongside "emails I received about the merger".
  A single search with a single phrasing will often miss relevant emails — when full coverage matters, always compose 2–4 parallel entries.

  ## Strategy for broad or unfocused queries
  If the user's question is too broad for semantic search to be meaningful on its own (e.g. "show me all emails from last week", "list everything from alice@example.com"):
  1. Keep a broad or descriptive \`search\` term, OR use the most relevant keyword you can derive.
  2. Add precise \`conditions\` (e.g. dateFrom/dateTo, fromSenders) to narrow the candidate set.
  3. Set \`limit\` to 300 to capture as many matching emails as possible.
  This combination is more reliable than relying on semantic relevance alone for listing or enumeration tasks.

  ## Complementing semantic search with KQL (msGraphKeywordSearchQueries)
  ALWAYS include at least one entry in both \`uniqueSemanticSearchQueries\` and \`msGraphKeywordSearchQueries\`. A single backend alone will miss results: semantic search may miss exact keyword hits; KQL will miss conceptual matches and attachment content.

  The two backends cover different ground and their results are merged — semantic results are ranked first, then enriched with the KQL body excerpt when the same email was matched by both:
  - **Semantic** excels at: conceptual relevance, synonyms, natural-language intent, content inside attachments.
  - **KQL** excels at: exact keyword matches, precise property filters, full body text excerpts.

  **How to translate a semantic query into complementary KQL:**
  1. Extract the most specific keywords from the semantic query and express them as \`subject:\` and/or \`body:\` filters.
  2. Mirror any structured conditions as KQL property filters (e.g. \`fromSenders\` → \`from:\`, date range → \`received>=\`/\`received<=\`, attachments → \`hasAttachment:true\`).
  3. Run multiple KQL queries in parallel for different angles: synonyms, subject-focus vs. body-focus, alternative keyword combinations.

  ## Scoping to a specific mailbox
  To search within a specific mailbox (own or delegated), set the top-level \`mailbox\` field on each query object — do NOT encode the mailbox in the \`search\` text, in \`conditions\`, or as \`mailbox:\` inside a KQL string (it is not a KQL property). Set \`mailbox\` on EVERY entry in both \`uniqueSemanticSearchQueries\` and \`msGraphKeywordSearchQueries\` when scoping to a delegated inbox.
  Always call \`list_mailboxes_and_directories\` first if you are unsure of the exact mailbox address.

  Example — user asks "list all emails in the shared bug-bash mailbox":
  - Semantic entry 1: \`{ mailbox: "bug-bash@example.com", search: "email", limit: 300 }\`
  - KQL query 1: \`{ mailbox: "bug-bash@example.com", kqlQuery: "kind:email", limit: 50 }\`
  The \`mailbox\` field is set on both entries — the search is scoped to that inbox on both backends.

  Example — user asks "emails about the Q2 budget in the shared finance mailbox":
  - Semantic entry 1: \`{ mailbox: "finance@example.com", search: "Q2 budget report", limit: 300 }\`
  - Semantic entry 2: \`{ mailbox: "finance@example.com", search: "quarterly financial summary", limit: 300 }\`
  - KQL query 1: \`{ mailbox: "finance@example.com", kqlQuery: "subject:\\"Q2 budget\\"" }\`
  - KQL query 2: \`{ mailbox: "finance@example.com", kqlQuery: "body:\\"budget\\" received>=2024-04-01 received<=2024-06-30" }\`
  Both the \`mailbox\` scoping and structured filters are expressed on every entry.

  Example — user asks "Q2 budget report from Alice":
  - Semantic entry 1: \`search: "Q2 budget report"\`, conditions: \`[{ fromSenders: { value: "alice@example.com", operator: "equals" } }]\`
  - Semantic entry 2: \`search: "quarterly financial summary"\`, conditions: \`[{ fromSenders: { value: "alice@example.com", operator: "equals" } }]\`
  - KQL query 1: \`from:alice@example.com subject:"Q2 budget"\`
  - KQL query 2: \`from:alice@example.com body:"budget report" received>=2024-04-01 received<=2024-06-30\`

  Example — user asks "emails from bob@example.com that mention 'sector rotation' in the subject":
  - Semantic entry 1: \`search: "sector rotation"\`, conditions: \`[{ fromSenders: { value: "bob@example.com", operator: "equals" } }]\`
  - Semantic entry 2: \`search: "sector allocation strategy"\`, conditions: \`[{ fromSenders: { value: "bob@example.com", operator: "equals" } }]\`
  - KQL query 1: \`from:bob@example.com subject:"sector rotation"\`
  - KQL query 2: \`from:bob@example.com subject:sector AND subject:rotation\`
  Notice how \`fromSenders\` is populated on every semantic entry rather than encoded only in the \`search\` text — that is the preferred shape whenever the sender is clearly named.

  By default search across ALL folders. Do not restrict to a specific folder unless the user asks.
  After returning results, inform the user that they can narrow the search to a specific folder if needed.

  To filter by folder, pass its name directly to the \`directories\` parameter — no need to call \`list_mailboxes_and_directories\` for well-known folders.
  Use these exact names: "Inbox", "Sent Items", "Drafts", "Archive", "Outbox", "Clutter", "Conversation History".
  Note: "Deleted Items", "Junk Email", and "Recoverable Items Deletions" are not synchronized — searching through them will not return results.
  For custom user-defined folders, call \`list_mailboxes_and_directories\` first to get the folder ID.

  If the response includes a "syncWarning", display it to the user before showing results so they understand results may be incomplete.
  If the response includes a "searchNotes", display it to the user after results — it contains context about the search run (e.g. excluded folders, partially unavailable mailboxes).

  ## Opening an email after search
  When the user asks to open, read, or see the full content of a specific email that appeared in the results, call \`open_email_by_id\` — pass the \`openEmailParams\` object from that result directly as the tool input. Do NOT tell the user you cannot access the email or that you lack mailbox access.`,
  toolFormatInformation: TOOL_FORMAT_INFORMATION,
});

export const META_MS_GRAPH = createMeta({
  icon: 'search',
  systemPrompt: `Searches Outlook emails using Microsoft Graph KQL queries. Returns matched emails with metadata and full body content in the \`text\` field — answer questions about email content directly from \`text\` without calling \`open_email_by_id\` unless the user explicitly asks to open an email.

  By default search across ALL folders. Do not restrict to a specific folder unless the user asks.
  After returning results, inform the user that they can narrow the search with more specific KQL terms if needed.

  Build precise KQL queries using supported property filters: from:, to:, cc:, subject:, body:, received>=, received<=, hasAttachment:, category:, participants:. Do NOT use folder: — it is not supported.
  For entity/name mentions that may appear anywhere in the email (e.g. "emails mentioning UBS", "where Zach Greenwald appears"), always include a body: entry — e.g. body:UBS or body:"Zach Greenwald". Use participants: when the name may appear in any address field.
  Combine clauses with AND/OR for complex searches. You can run multiple KQL queries in parallel (up to 10) for broader coverage.
  If the response includes a "searchNotes", display it to the user after results — it contains context about the search run (e.g. excluded folders, partially unavailable mailboxes).

  ## Scoping to a specific mailbox
  To search within a specific mailbox (own or delegated), set the top-level \`mailbox\` field on the query object — do NOT put mailbox: inside the kqlQuery string (it is not a KQL property and will be stripped).
  Always call \`list_mailboxes_and_directories\` first if you are unsure of the exact mailbox address.

  ## Examples

  **User asks "list all emails in the shared bug-bash mailbox":**
  - Query 1: \`{ mailbox: "bug-bash@example.com", kqlQuery: "kind:email", limit: 50 }\`

  **User asks "emails from Alice about the Q2 budget":**
  - Query 1: \`{ kqlQuery: "from:alice@example.com subject:\\"Q2 budget\\"" }\`
  - Query 2: \`{ kqlQuery: "from:alice@example.com body:\\"budget\\" received>=2024-04-01 received<=2024-06-30" }\`
  Run both in parallel — one anchors on subject, the other on body with a date range.

  **User asks "find emails mentioning UBS from last month":**
  - Query 1: \`{ kqlQuery: "body:UBS received>=2026-04-01 received<=2026-04-30" }\`
  - Query 2: \`{ kqlQuery: "subject:UBS received>=2026-04-01 received<=2026-04-30" }\`
  Use both subject: and body: in parallel — the entity may appear in either place.

  **User asks "unread emails with attachments from the DevOps team this week":**
  - Query 1: \`{ kqlQuery: "from:devops@acme.com hasAttachment:true received>=2026-05-19" }\`
  Note: isRead/read: are not supported KQL properties — filter by read status is not possible via KQL.

  **User asks "emails where Zach Greenwald is mentioned":**
  - Query 1: \`{ kqlQuery: "body:\\"Zach Greenwald\\"" }\`
  - Query 2: \`{ kqlQuery: "participants:\\"Zach Greenwald\\"" }\`
  Use body: for mentions in the email text and participants: for appearances in address fields.

  ## Opening an email after search
  When the user asks to open, read, or see the full content of a specific email that appeared in the results, call \`open_email_by_id\` — pass the \`openEmailParams\` object from that result directly as the tool input. Do NOT tell the user you cannot access the email or that you lack mailbox access.`,
  toolFormatInformation: TOOL_FORMAT_INFORMATION,
});
