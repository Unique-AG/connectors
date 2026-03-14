import path from 'node:path';
import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

const packagesDir = path.resolve(__dirname, '../../packages');

export default defineConfig({
  ...globalConfig,
  resolve: {
    alias: {
      '~': path.resolve(__dirname, './src'),
      '@unique-ag/aes-gcm-encryption': path.join(packagesDir, 'aes-gcm-encryption/src/index.ts'),
      '@unique-ag/instrumentation': path.join(packagesDir, 'instrumentation/src/index.ts'),
      '@unique-ag/logger': path.join(packagesDir, 'logger/src/index.ts'),
      '@unique-ag/mcp-oauth': path.join(packagesDir, 'mcp-oauth/src/index.ts'),
      '@unique-ag/mcp-server-module': path.join(packagesDir, 'mcp-server-module/src/index.ts'),
      '@unique-ag/probe': path.join(packagesDir, 'probe/src/index.ts'),
      '@unique-ag/unique-api': path.join(packagesDir, 'unique-api/src/index.ts'),
      '@unique-ag/utils': path.join(packagesDir, 'utils/src/index.ts'),
    },
  },
  test: {
    ...globalConfig.test,
    root: './',
    include: ['**/*.spec.ts'],
    setupFiles: ['./test/setup.ts'],
  },
});
