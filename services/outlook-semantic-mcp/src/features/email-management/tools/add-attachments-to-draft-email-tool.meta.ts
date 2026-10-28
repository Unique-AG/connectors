import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'paperclip',
  systemPrompt: `### When to Use \`add_attachments_to_draft_email\`
    Use it to attach files to a draft that already exists. To create a new draft with attachments, pass them to \`draft_email\` instead. To change the text or recipients of a draft use \`update_draft_email\`; to remove files use \`remove_attachments_from_draft_email\`.

    ### Attachments
    Each entry in \`attachments\` has a \`fileName\` (the name shown on the attachment, with extension) and \`data\`, a URI identifying the content:
    - \`unique://content/{contentId}\` — a file from the Unique knowledge base.
    - \`data:[mediatype];base64,<base64data>\` — inline base64 content.

    External URLs (\`https://\`) are **not supported**. Adding a file whose name is already on the draft attaches a second copy — remove the old one first if the user wants to replace it.

    ### Failed Attachments
    When \`attachmentsFailed\` is non-empty, tell the user which files failed and why.`,
});
