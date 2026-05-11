import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'building',
  systemPrompt:
    "Searches the Kyckr global company registry by name or registration number. Use when the user wants to find a company, verify it exists, or obtain its Kyckr ID. Either `name` or `companyNumber` must be provided. Pass `isoCode` (ISO 3166 alpha-2, e.g. 'GB', 'AU') to search a specific jurisdiction directly at its registry. Without `isoCode`, Kyckr performs a global search over its stored data — confirm hits by re-querying with the jurisdiction's `isoCode` before relying on company status. The returned `id` is the KyckrId required by every other Kyckr tool (lite/enhanced profile, documents, orders).",
});
