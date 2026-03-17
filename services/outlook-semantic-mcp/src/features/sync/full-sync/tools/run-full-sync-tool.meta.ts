import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'play',
  systemPrompt:
    "Triggers a full re-sync of the user's Outlook inbox. Use this when the user reports missing emails, stale search results, or after a long period of inactivity. After triggering, call `sync_progress` to monitor ingestion status.",
});
