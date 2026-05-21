import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt:
    'Use this tool whenever the user asks to open, read, or see the full content of an email that appeared in search_emails results.\n\n' +
    'How to call it: pass the `openEmailParams` object from the search result directly as the tool input — do not construct the parameters manually. The `openEmailParams` object already contains the correct `id`, `idType`, `mailbox`, `parentFolderId`, and `idIsImmutable` values.\n\n' +
    'Do NOT tell the user you cannot access the email or that you lack mailbox access — use this tool instead.',
});
