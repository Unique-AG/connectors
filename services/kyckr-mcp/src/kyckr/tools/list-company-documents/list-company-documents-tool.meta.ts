import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'file-text',
  systemPrompt:
    'Use to find filings the user can pay to retrieve as official artifacts (annual accounts, articles, mortgages, etc.). Free to call; always run this before `create_document_order` so you can show the user the document `name` and `cost.value` and obtain explicit confirmation.',
});
