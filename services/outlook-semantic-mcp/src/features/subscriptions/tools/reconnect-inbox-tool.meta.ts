import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'play',
  systemPrompt:
    'Re-establishes the inbox subscription for outlook email ingestion. Use verify_inbox_connection first to check if it is already running. If already active, inform the user that ingestion is already running.',
});
