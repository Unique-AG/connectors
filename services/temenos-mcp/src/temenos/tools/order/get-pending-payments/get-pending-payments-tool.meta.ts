import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'clock',
  systemPrompt:
    'Use to see payments pending processing. Filter by debitAccountId or creditAccountId to find payments for a specific account.',
});
