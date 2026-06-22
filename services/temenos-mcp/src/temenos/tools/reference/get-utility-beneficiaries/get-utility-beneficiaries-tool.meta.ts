import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'user-check',
  systemPrompt:
    'Use to look up pre-defined utility beneficiaries. Filter by owningCustomerId to find beneficiaries linked to a specific customer, or by beneficiaryIBAN for international transfers.',
});
