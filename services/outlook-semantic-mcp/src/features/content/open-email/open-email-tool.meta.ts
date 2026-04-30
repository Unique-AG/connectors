import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt:
    'Use this tool to read the complete body of an email that appeared in search_emails results. Copy the `backend` field from the search result exactly as-is. Then pass the identifier that matches the backend:\n- `uniqueContentId` when backend is `Unique`\n- `msGraphMessageId` when backend is `MsGraph`\nDo not invent or modify these values — always copy them verbatim from the search result.',
});
