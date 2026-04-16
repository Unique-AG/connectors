import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current status of the inbox connection for Outlook emails. Use the returned status to determine whether to suggest reconnecting, removing the connection, or taking no action.',
});
