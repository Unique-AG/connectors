import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  test: {
    ...globalConfig.test,
    root: './',
    include: ['**/*.e2e-spec.ts'],
    setupFiles: ['./test/setup.e2e.ts'],
  },
});
