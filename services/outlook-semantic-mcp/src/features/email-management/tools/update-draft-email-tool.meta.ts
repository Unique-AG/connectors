import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt: `### When to Use \`update_draft_email\`
    Use it when the user wants to change a draft that already exists — "make it more polite", "add Maria in copy", "change the subject", "fix the second paragraph" — whether you created the draft with \`draft_email\` earlier in the conversation or the user wrote it in Outlook. Do not create a new draft for an edit.

    ### Read Before You Edit
    1. **Find the draft.** If you created it in this conversation, use the \`draftId\` that \`draft_email\` returned and open it with \`open_email\` as \`{ id: draftId, bodyContentType: "html" }\` (plus \`mailbox\` if you passed one when creating it). Otherwise call \`search_emails\` restricted to the \`Drafts\` folder and pick the result with \`isDraft: true\`.
    2. **Open the live message. This is mandatory.** Pass \`openEmailParams\` directly to \`open_email\`. It reads the live Graph message. When \`isDraft\` is true, \`text\` is HTML. \`chunks\`, when present, are matched ingested passages — do not rewrite the body from them.
    3. **Check \`metadata.isDraft\`.** If it is false the message was sent and cannot be edited.
    4. **Edit the HTML and send it back.** Copy \`openEmailParams.id\` to \`draftId\`, and copy \`idIsImmutable\` and \`mailbox\` when they are set. \`content\` replaces the whole HTML body, so change only what the user asked to change and keep styles, tables, the signature, the quoted thread, and \`cid:\` images. Recipient lists replace the whole list: pass the full new list, not only the additions.

    ### Attachments
    This tool does not touch attachments. Use \`add_attachments_to_draft_email\` to add files and \`remove_attachments_from_draft_email\` to remove them. Inline images are left in place unless the user explicitly asked to remove them.

    ### Body Formatting
    \`content\` is **HTML**, stored exactly as you send it. Do not convert the body to Markdown and do not write a new body from scratch. Use the HTML \`open_email\` returned. Fragment only — no \`html\`, \`head\`, or \`body\` wrappers. Use \`<p>\` for paragraphs, \`<br>\` for line breaks, \`<strong>\` bold, \`<em>\` italic, \`<ul>\`/\`<ol>\`/\`<li>\` lists, and \`<a href="https://example.com">\` links when you add formatting the original body did not have.`,
  toolFormatInformation: `## Format for Draft Update Confirmation
  📩 **{subject}**[ — [Open in Outlook]({webLink})]
  {message}

  Rules:
  - **subject**: the subject you passed, otherwise the subject you read with \`open_email\`.
  - **Open in Outlook link**: include only when \`webLink\` is present. Use it as the href without modifying it.
  - **message**: display the \`message\` from the tool output.
`,
});
