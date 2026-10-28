import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt: `### When to Use \`update_draft_email\`
    Use it when the user wants to change a draft that already exists — "make it more polite", "add Maria in copy", "change the subject", "fix the second paragraph" — whether you created the draft with \`draft_email\` earlier in the conversation or the user wrote it in Outlook. Do not create a new draft for an edit.

    ### Read Before You Edit
    1. **Find the draft.** If you created it in this conversation, use the \`draftId\` that \`draft_email\` returned. Otherwise call \`search_emails\` restricted to the \`Drafts\` folder and pick the result with \`isDraft: true\`. Use its \`msGraphMessageId\` as \`draftId\`, \`openEmailParams.idIsImmutable\` as \`idIsImmutable\`, and \`sourceMailbox\` as \`mailbox\` when it is not the user's own mailbox.
    2. **Read it with \`open_email\`** and check \`metadata.isDraft\`. If it is false the message was sent and cannot be edited.
    3. **Edit.** \`content\` replaces the whole body, including the quoted earlier thread of a reply draft, so rewrite from what you read and keep everything the user did not ask to change. Recipient lists replace the whole list: pass the full new list, not only the additions.

    ### Attachments
    This tool does not touch attachments. Use \`add_attachments_to_draft_email\` to add files and \`remove_attachments_from_draft_email\` to remove them.

    ### Body Formatting
    \`content\` is **Markdown**, converted to HTML on the server. Do not write raw HTML tags; they are shown as literal text.`,
  toolFormatInformation: `## Format for Draft Update Confirmation
  📩 **{subject}**[ — [Open in Outlook]({webLink})]
  {message}

  Rules:
  - **subject**: the subject you passed, otherwise the subject you read with \`open_email\`.
  - **Open in Outlook link**: include only when \`webLink\` is present. Use it as the href without modifying it.
  - **message**: display the \`message\` from the tool output.
`,
});
