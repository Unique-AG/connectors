import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'file-text',
  systemPrompt:
    'Use only after the user has explicitly approved both the document and the credit cost shown by `list_company_documents`. The only tool that spends credits *and* creates state on Kyckr — never call speculatively, never retry on transient failure without a fresh confirmation. After a successful call, poll `get_order(data.orderId)` until it resolves.',
});
