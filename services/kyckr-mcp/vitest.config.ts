import path from 'node:path';
import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  resolve: {
    alias: {
      '~': path.resolve(__dirname, './src'),
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
