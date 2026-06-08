import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt: `### When to Use \`draft_email\` Tool
      Use \`draft_email\` tool whenever the user's intent involves composing, writing, or responding to an email — even if they don't explicitly say "write an email." This includes but is not limited to phrases like:
    - "Write an email to..."
    - "Draft a message to..."
    - "Reply to..." / "Answer to..."
    - "Send a quick note to..."
    - "Let [person] know that..."
    - "Tell [person] that..."
    - "Get back to [person] about..."
    - "Follow up with [person]..."
    - "Make sure my emails are answered"
    - "Answer to [person] that..."
    If the user refers to a person and describes content they want communicated, treat it as an email drafting request. There is no "send email" tool — drafting is the final action.

    ### Resolving Email Recipients
    This section applies to \`type: "draft"\` only. For \`type: "reply"\`, skip recipient resolution entirely — pass the \`msGraphMessageId\` directly as \`inReplyToMessageId\` and Graph pre-fills all recipients.

    **Do not ask the user for confirmation before searching.** Act immediately.
    For new drafts (\`type: "draft"\`), you **must** resolve the recipient's email address before drafting:
    1. **Explicit address provided**: If the user gave you an email address directly, use it.
    2. **No address provided — search immediately**: If the user refers to a person by name, role, or organization but did not provide an email address, **immediately** call the \`search_emails\` tool. Do NOT ask the user whether you should search. Do NOT present a plan or options. Do NOT ask for confirmation. Just search.
    3. **Ambiguous results**: If \`search_emails\` returns multiple possible matches, present them to the user and ask which one to use.
    4. **No results from search_emails**: If \`search_emails\` returns no relevant results, call \`lookup_contacts\` as a last resort to find the recipient's email address.
    5. **Still no results**: Only if both \`search_emails\` and \`lookup_contacts\` return no relevant results, ask the user to provide the email address manually.
    Never guess or fabricate an email address. Never skip step 2. Never ask for permission to search — just do it.

    ### Drafting Behavior
    When the user asks you to write, reply to, or draft an email:
    1. **Always reason first: reply or new draft?** Before anything else, check the conversation context:
       - Is there a retrieved email (with a \`msGraphMessageId\`) that the user is **directly reacting to** in this message?
       - If yes → use \`type: "reply"\` with that \`msGraphMessageId\`. Do not ask for recipient or subject.
       - If no → use \`type: "draft"\` and resolve the recipient as described below.
       Use \`type: "reply"\` only when the user's current message is a clear reaction to a specific email just shown in the conversation. Do not default to reply just because some email happens to be in context from an earlier search — the user must be explicitly responding to it.
    2. **Act immediately. Do not ask any questions before drafting.** No clarifications, no confirmations, no options, no plans. Just do it.
    3. **Infer everything you can** from the user's message — tone, intent, level of formality, content. Use reasonable defaults for anything not specified.
    4. **Draft a single email right away** and present it using the format specified below.
    5. **The user will correct you if needed.** Trust that the user will tell you if something is wrong. Do not try to get it perfect on the first ask — getting it done fast is more important.
    The **only** exception: if after searching with \`search_emails\` and \`lookup_contacts\` you still cannot determine the recipient's email address, ask the user for it. That is the only reason to pause and ask a question.

    ### What \`draft_email\` Does
    Creates a draft email in the user's Outlook mailbox. The draft is saved and can be reviewed or sent later.
    - For \`type: "draft"\`: provide subject, body content (Markdown), and at least one recipient. Optionally include CC recipients and attachments.
    - For \`type: "reply"\`: provide only the body content (Markdown) and the \`inReplyToMessageId\`. Graph pre-fills all recipients and the subject — no need to specify them.

    ### Shared Mailbox and Reply Drafts
    \`draft_email\` requires a \`type\` field that selects the drafting mode:

    1. **\`type: "draft"\`** — fresh draft. \`toRecipients\` is required. Optionally pass \`mailbox\` to create the draft in a shared mailbox instead of the signed-in user's own mailbox.

    2. **\`type: "reply"\`** — reply-all draft. Pass \`inReplyToMessageId\` with the \`msGraphMessageId\` value from \`search_emails\` or \`outlook_email_search\` results. Graph pre-fills all original recipients — do **not** pass \`toRecipients\` or \`ccRecipients\`. If the email you are replying to came from a shared or delegated mailbox (i.e. \`sourceMailbox\` is non-null in the search result), you **must** pass that same value as \`mailbox\` — otherwise Graph will look up the message under \`/me\` and return a 404. Omit \`mailbox\` only when replying to an email from the signed-in user's own mailbox (\`sourceMailbox\` is null).

    ### Replying to a Received Email (Most Common Use Case)
    **Replying to an email the user just read or retrieved is the most frequent reason to call \`draft_email\`.** Recognise these natural language patterns as reply intent — even without the word "reply":
    - "Reply to this email"
    - "Draft a reply to [person]'s email"
    - "Respond to this" / "Respond to [person]"
    - "Get back to [person] about this"
    - "Answer this email" / "Answer [person]"
    - "Write back to them"

    Note: "Tell [person] that…" and "Let [person] know that…" are **not** automatically reply triggers — the named person may differ from the sender. Treat them as reply intent only when the named person is clearly the sender of the retrieved email; otherwise draft a new email to that person.

    When reply intent is detected and an email was recently retrieved:
    1. **Do not ask for the recipient or subject.** Use \`type: "reply"\` and pass the \`msGraphMessageId\` of the retrieved email as \`inReplyToMessageId\` — Graph pre-fills all recipients and subject automatically.
    2. **Draft and call \`draft_email\` immediately.** The user should not have to re-specify the recipient, subject, or thread context.

    Failure to use \`type: "reply"\` with the retrieved email's \`msGraphMessageId\` is the most common mistake — avoid it.

    #### Examples — when to use type: "reply"

    Context: conversation contains an email with msGraphMessageId="AAMk123", from nick@example.com, subject "Payroll System Migration Plan"
    User: "Draft a reply to this email, tell him we need to reduce ADP cost to 76k max"
    Action: recipientsData={ type="reply", inReplyToMessageId="AAMk123" }, body addresses the cost constraint (Graph fills recipient and subject)

    Context: conversation contains an email with msGraphMessageId="AAMk456", from sarah@acme.com, subject "Re: Q2 Budget Review"
    User: "Respond to this — confirm the meeting is on Thursday"
    Action: recipientsData={ type="reply", inReplyToMessageId="AAMk456" }, body confirms the meeting (Graph fills recipient and subject as-is, no duplicate "Re:")

    Context: conversation contains an email with msGraphMessageId="AAMk789", from investor@fund.com, subject "Due Diligence Update"
    User: "Get back to them — say we'll have the documents ready by Friday"
    Action: recipientsData={ type="reply", inReplyToMessageId="AAMk789" }, body states Friday deadline

    Context: conversation contains an email with msGraphMessageId="AAMk321", from alex@partner.com, subject "Integration Timeline"
    User: "Respond to this and ask for more details about the timeline"
    Action: recipientsData={ type="reply", inReplyToMessageId="AAMk321" }, body requests timeline details

    #### Examples — when to use type: "draft" (new email, no prior email in context)

    Context: no prior email in conversation
    User: "Write an email to john@example.com about the upcoming product launch"
    Action: recipientsData={ type="draft", toRecipients=[john@example.com], subject inferred from content }

    Context: no prior email in conversation
    User: "Draft a message to the finance team asking for the Q1 numbers"
    Action: search for finance team address first, then recipientsData={ type="draft", toRecipients=[resolved address], subject inferred }

    Context: no prior email in conversation
    User: "Send a quick note to Maria letting her know the contract is signed"
    Action: search for Maria's email address first, then recipientsData={ type="draft", toRecipients=[resolved address], subject inferred }

    ### Body Formatting
    The \`content\` field is **Markdown**. It is converted to HTML on the server before being sent to Outlook, so use Markdown syntax for all formatting — do **not** write raw HTML tags (\`<br>\`, \`<p>\`, \`<strong>\`, etc.); they will be shown as literal text.

    Supported:
    - Blank line between paragraphs.
    - \`**bold**\`, \`*italic*\`, \`\`inline code\`\`.
    - Bullet lists with \`-\` and numbered lists with \`1.\`.
    - Links as \`[label](https://example.com)\`.
    - Blockquotes with \`>\`.

    Example of a well-formatted body:
    \`\`\`markdown
    Hi Sarah,

    Please find attached the **minutes** from the meeting for the inception of the new fund.

    Key points discussed:
    - Fund structure and target size
    - Investment thesis and sector focus
    - Timeline for first close

    Next steps:
    1. Review the attached minutes
    2. Share feedback by end of week
    3. Schedule a follow-up call

    Let me know if you have any questions. More info on our [website](https://unique.ai).

    Best regards,
    Nicolae
    \`\`\`

    Use blank lines to separate paragraphs. Inside the signature, a single line break between "Best regards," and the name is preserved as a line break.

    ### Attachments
    To attach files, pass an array of objects in the \`attachments\` field. Each object must have:
    - \`fileName\`: the name that will appear on the attachment (e.g. \`report.pdf\`)
    - \`data\`: a URI identifying the file content. Supported URI schemes:
      - **Unique content**: \`unique://content/{contentId}\` — attach a file from the Unique knowledge base using its content ID. Example: \`unique://content/cont_j23i0ifr44sdn7cz97ubleb7\`.
      - **Data URIs**: \`data:[mediatype];base64,<base64data>\` — inline base64-encoded content.

    External URLs (\`https://\`) are **not supported**. Do not pass raw content IDs — always use the \`unique://\` URI scheme for Unique knowledge base files.

    ### Failed Attachments
    The response may include an \`attachmentsFailed\` array when one or more attachments could not be added. The draft is still created in that case. Each entry has a \`fileName\` and a \`reason\`. When \`attachmentsFailed\` is non-empty, inform the user which files failed and why, for example:
    > ⚠️ The following attachments could not be added:
    > - **report.pdf**: File not found in the knowledge base.`,
  toolFormatInformation: `## Format for Draft Confirmation
  When presenting the result of a created draft, always use the following format:
  📩 **{subject}**[ — [Open in Outlook]({webLink})]
  {message}

  Rules:
  - **subject**: For \`type: "draft"\`, use the subject from the tool input. For \`type: "reply"\`, use the subject of the original email from the conversation context (Graph pre-fills it; the tool output does not return it).
  - **Open in Outlook link**: Include only when \`webLink\` is present in the tool output. Use the \`webLink\` value directly as the href — do not construct or modify it.
  - **message**: Display the \`message\` from the tool output (e.g. "Draft email created successfully.").
  - If \`attachmentsFailed\` is non-empty, list each failed attachment below the message.
`,
});
