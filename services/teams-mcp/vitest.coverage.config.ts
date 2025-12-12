import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  test: {
    ...globalConfig.test,
    root: './',
    include: ['**/*.spec.ts', 'test/**/*.e2e-spec.ts'],
    setupFiles: ['./test/setup.ts'],
    coverage: {
      enabled: true,
      all: false,
      provider: 'istanbul',
      include: ['src/**', 'test/**'],
      reporter: ['json-summary'],
    },
  },
  resolve: {
    alias: {
      '@generated': resolve(__dirname, './@generated'),
    },
  },
});
