import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt:
    'Search results (`search_emails`, `fetch_next_search_pages`) only carry partial content in `text`: matched passages and/or a short body preview. Use this tool to read the full body of any result whose `text` does not clearly answer the question, and whenever the user asks to open, read, or see an email.\n\n' +
    'How to call it: pass the `openEmailParams` object from the search result directly as the tool input — do not construct the parameters manually. The `openEmailParams` object already contains the correct `id`, `idType`, `mailbox`, `parentFolderId`, and `idIsImmutable` values.\n\n' +
    'Before editing a draft with `update_draft_email`, open it with this tool first: `metadata.isDraft` tells you whether the message is still an unsent draft, and the body and recipients you read are what the edit replaces. `metadata.attachments` lists the file names a draft currently carries (for emails ingested before attachment names were stored it can be empty even when `hasAttachments` is true), which `remove_draft_email_attachments` takes.\n\n' +
    'Do NOT tell the user you cannot access the email or that you lack mailbox access — use this tool instead.',
});
