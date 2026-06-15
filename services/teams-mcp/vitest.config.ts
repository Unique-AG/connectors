import path from 'node:path';
import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  resolve: {
    alias: {
      '~': path.resolve(__dirname, './src'),
      // Resolve the workspace package from source so tests run without first
      // building its `dist` (the service `build` is `nest build`, which does
      // not build dependencies). Mirrors outlook-semantic-mcp's config.
      '@unique-ag/mcp-server-module': path.resolve(
        __dirname,
        '../../packages/mcp-server-module/src/index.ts',
      ),
    },
  },
  test: {
    ...globalConfig.test,
    root: './',
    include: ['**/*.spec.ts'],
    setupFiles: ['./test/setup.ts'],
  },
});
