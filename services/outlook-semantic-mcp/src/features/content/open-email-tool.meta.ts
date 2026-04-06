import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'mail',
  systemPrompt:
    'Retrieves the full content of an ingested Outlook email by its content ID. Use the ID returned by os_mcp_search_emails.',
});
