import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'shield',
  systemPrompt:
    'Use to look up guarantee requests. Filter by customerId to find all guarantees for a specific customer, or by eventStatus to see only approved or pending items.',
});
