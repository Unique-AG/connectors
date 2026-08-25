import path from 'node:path';
import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  resolve: {
    alias: {
      '~': path.resolve(__dirname, './src'),
      // Workspace packages are never built before a test run (CI installs and
      // then tests), so `main: dist/index.js` cannot resolve. A spec importing a
      // *.tool.ts file needs the `@Tool` decorator as a runtime value, so point
      // the import at the package source.
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
