import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'building',
  systemPrompt:
    'Fetches a paid Lite company profile from Kyckr after a company has been identified with `search_companies`. Use it for basic verified registry details such as name, company number, address, status, legal form, activities, and registration authority. It does not include directors, shareholders, or UBOs; use `get_enhanced_profile` for those. This call may spend Kyckr credits, so avoid speculative repeats.',
});
