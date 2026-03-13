import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'stop',
  systemPrompt:
    'Removes the inbox connection for outlook emails. After removing, new emails will no longer be ingested. Use verify_inbox_connection first to check if it is running.',
});
