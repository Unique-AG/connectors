import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'file-text',
  systemPrompt:
    'Use to poll a `Pending` order until it resolves to `Success` (download links populated) or `Failed`. Also useful for re-fetching links for a previously completed order. Treat `statusCode: 410` as terminal — the document is gone, do not retry.',
});
