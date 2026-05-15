import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'building',
  systemPrompt:
    "Always the first step when the user names a company. Use the result's `id` as the `kyckrId` for any downstream tool. For status decisions, confirm with a jurisdiction-specific re-search (`isoCode` set) before treating a global-search hit as current - global search runs over Kyckr's stored snapshot.",
});
