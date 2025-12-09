import { defineConfig } from 'vitest/config';
import { globalConfig } from '../../vitest.config';

export default defineConfig({
  ...globalConfig,
  test: {
    ...globalConfig.test,
    root: './',
    include: ['**/*.spec.ts'],
    setupFiles: ['./test/setup.ts'],
    coverage: {
      provider: 'v8',
      enabled: true,
      reporter: [
        'text',
        'text-summary',
        'html',
        'json',
        'json-summary',
        'lcov'
      ],
      reportsDirectory: './coverage',
      include: ['src/**/*.ts'],
      exclude: [
        'src/**/*.spec.ts',
        'src/**/*.e2e-spec.ts',
        'src/**/*.d.ts',
        'src/main.ts',
        'src/**/*.module.ts',
        'src/**/*.interface.ts',
        'src/**/*.enum.ts',
        'src/**/*.type.ts',
        'src/**/*.constant.ts',
      ],
      all: true,
      clean: true,
      skipFull: false,
      reportOnFailure: true,
      watermarks: {
        lines: [70, 85],
        functions: [70, 85],
        branches: [70, 85],
        statements: [70, 85]
      }
    },
  },
});
