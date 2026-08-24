import path from 'node:path';
import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  resolve: {
    alias: {
      '~': path.resolve(__dirname, './src'),
      // CI runs `pnpm build` inside this service only, so workspace packages have
      // no `dist` when the suite runs. Resolve to source, as outlook-semantic-mcp
      // does, so a spec can import a module that pulls in the decorator.
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
