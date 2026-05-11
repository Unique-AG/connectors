import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'building',
  systemPrompt:
    "Use after `search_companies` when the user needs verified company identification (name, number, address, dates, legal form, status). Spends credits — confirm intent if there's any ambiguity, and prefer caching the result over re-fetching. If the user asks about directors / shareholders / UBOs, use `get_enhanced_profile` instead.",
});
