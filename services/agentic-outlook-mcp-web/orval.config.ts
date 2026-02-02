import { defineConfig } from 'orval';

export default defineConfig({
  agenticOutlookMcp: {
    input: {
      target: '../agentic-outlook-mcp/openapi.json',
    },
    output: {
      client: 'fetch',
      mode: 'tags-split',
      target: './src/@generated',
      override: {
        mutator: {
          path: './src/lib/custom-fetch.ts',
          name: 'customFetch',
        },
      },
    },
  },
});
