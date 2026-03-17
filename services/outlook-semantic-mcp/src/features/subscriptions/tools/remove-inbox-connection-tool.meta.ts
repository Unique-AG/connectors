import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'stop',
  systemPrompt:
    'Removes the inbox connection for Outlook emails. After removing, new emails will no longer be ingested.',
});
