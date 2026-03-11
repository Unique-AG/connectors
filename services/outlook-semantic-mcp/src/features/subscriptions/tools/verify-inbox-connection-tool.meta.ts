import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'status',
  systemPrompt:
    'Returns the current status of the inbox connection for outlook emails. Use this to verify if email ingestion is running before suggesting to connect or remove the inbox connection.',
});
