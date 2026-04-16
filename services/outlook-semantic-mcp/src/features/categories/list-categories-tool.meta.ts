import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'tag',
  systemPrompt:
    'Returns the list of Outlook mail category names configured for the user. Use category names when filtering emails by category. Call this tool when the user wants to know which categories are available or wants to search emails by category.',
});
