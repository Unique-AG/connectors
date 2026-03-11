import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current full sync progress including inbox configuration and ingestion statistics. Use this to monitor how many emails have been processed and their ingestion states.',
});
