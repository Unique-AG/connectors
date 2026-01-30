import { defineConfig } from 'orval';

export default defineConfig({
  n8nApi: {
    input: {
      target: './src/n8n-api/n8n-api-v1.json',
      filters: {
        tags: ['Workflow', 'Execution'],
      },
    },
    output: {
      client: 'fetch',
      mode: 'single',
      target: './src/n8n-api/@generated/n8n-api.ts',
      baseUrl: false,
    },
  },
  n8nApiZod: {
    input: {
      target: './src/n8n-api/n8n-api-v1.json',
      filters: {
        tags: ['Workflow', 'Execution'],
      },
    },
    output: {
      client: 'zod',
      mode: 'single',
      target: './src/n8n-api/@generated/n8n-api.zod.ts',
    },
  },
});
