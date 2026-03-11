import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'searct',
  systemPrompt: `Searches ingested Outlook emails semantically. Use conditions to filter by sender, date, recipient, folder, attachments, or category. Returns matched passages from emails with metadata. Call list_folders first to get folder IDs for directory filtering.

  Per default ALWAYS search in the inbox only.

  Use the ID of that folder for the "directories" parameter
  But ALWAYS ask at the end if other folders should be considered for the search`,
  toolFormatInformation: `## Email Display Rules
  ALWAYS follow these rules when displaying results from \`search_emails\` or when referencing information extracted from emails.
  ### Format for listing emails
  When listing multiple emails, format each as a compact block — NEVER use a markdown table:
  📩 **{Subject}** [open](https://outlook.office.com/owa/?ItemID={emailId}&exvsurl=1&viewmodel=ReadMessageItem)
  {From}
  {Date formatted as "Mon DD, YYYY at HH:MM AM/PM"}
  > {Short summary, max 1 sentence ending with ...}
  - Show most recent emails first.
  - Separate each email with a blank line.
  - The summary should be a single short sentence from the body. If no body content exists, omit the summary line entirely.
  ### Format when extracting or summarizing information from emails
  When the user asks a question and you answer using information found in emails (e.g. "What did Sarah say about the budget?", "When is the maintenance window?", "Summarize my conversation with Marco"), you MUST:
  - Write your answer in natural language.
  - ALWAYS include a link to EVERY source email you referenced, inline or at the end.
  - Use this format for inline references: [open email](https://outlook.office.com/owa/?ItemID={emailId}&exvsurl=1&viewmodel=ReadMessageItem)
  Example — user asks "What did Marco say about the partnership agreement?":
  Marco suggested a few changes to Section 3 of the partnership agreement, specifically around the liability clause and payment terms. He asked to schedule a call to discuss before signing. [open email](https://outlook.office.com/owa/?ItemID=AAkALgAA...&exvsurl=1&viewmodel=ReadMessageItem)
  Example — user asks "Summarize my recent emails with the DevOps team":
  You have 2 recent emails from DevOps:
  1. **Server maintenance** is scheduled for March 12 from 2:00–5:00 AM UTC on the production cluster. [open email](https://outlook.office.com/owa/?ItemID=AAkALgAA...&exvsurl=1&viewmodel=ReadMessageItem)
  2. **Deployment pipeline** was updated — the new CI/CD config requires all teams to re-trigger their staging builds. [open email](https://outlook.office.com/owa/?ItemID=AAkALgBB...&exvsurl=1&viewmodel=ReadMessageItem)
  ### Link rules (apply to ALL formats above)
  - URL pattern: \`https://outlook.office.com/owa/?ItemID={emailId}&exvsurl=1&viewmodel=ReadMessageItem\`
  - \`{emailId}\` is the \`emailId\` field from the search result. Use it as-is, no encoding needed.
  - NEVER show raw IDs (emailId, folderId, contentId) to the user.
  - NEVER display email results or reference email content without a link to the original email.
  ### Full listing example
  📩 **Q2 Budget Approval Needed** [open](https://outlook.office.com/owa/?ItemID=AAkALgAA...&exvsurl=1&viewmodel=ReadMessageItem)
  Sarah Chen (sarah.chen@acme.com)
  Mar 8, 2026 at 2:15 PM
  > Please review the attached Q2 budget proposal and approve by EOD Friday...
  📩 **Re: Partnership Agreement Draft** [open](https://outlook.office.com/owa/?ItemID=AAkALgBB...&exvsurl=1&viewmodel=ReadMessageItem)
  Marco Rossi (marco.rossi@external-partner.io)
  Mar 7, 2026 at 11:42 AM
  > We've reviewed Section 3 and have a few suggested changes to the liability clause...
  📩 **Onboarding Schedule - New Hires March 2026** [open](https://outlook.office.com/owa/?ItemID=AAkALgCC...&exvsurl=1&viewmodel=ReadMessageItem)
  HR Team (hr@acme.com)
  Mar 6, 2026 at 9:00 AM
  > Three new team members are joining next Monday, onboarding schedule attached...
  📩 **Accepted: Product Roadmap Review** [open](https://outlook.office.com/owa/?ItemID=AAkALgDD...&exvsurl=1&viewmodel=ReadMessageItem)
  Priya Patel (priya.patel@acme.com)
  Mar 5, 2026 at 4:30 PM
  📩 **Server Maintenance Window - March 12** [open](https://outlook.office.com/owa/?ItemID=AAkALgEE...&exvsurl=1&viewmodel=ReadMessageItem)
  DevOps (devops-alerts@acme.com)
  Mar 4, 2026 at 8:00 AM
`,
});
