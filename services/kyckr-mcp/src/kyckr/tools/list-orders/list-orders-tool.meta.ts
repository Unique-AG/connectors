import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'file-text',
  systemPrompt:
    'Use to find a prior order when the user references one by company or date but no `orderId` is in context, or to recover download links for a recently completed order. If you already know the `orderId`, prefer `get_order`.',
});
