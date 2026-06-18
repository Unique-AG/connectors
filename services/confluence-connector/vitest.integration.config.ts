import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  test: {
    ...globalConfig.test,
    root: './',
    include: ['**/*.integration-spec.ts'],
    setupFiles: ['./test/setup.integration.ts'],
  },
});
