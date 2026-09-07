import { vi } from 'vitest';

vi.mock('@nestjs/common', async () => {
  const actual = await vi.importActual<typeof import('@nestjs/common')>('@nestjs/common');
  return {
    ...actual,
    Logger: vi.fn(
      class MockLogger {
        public readonly log = vi.fn();
        public readonly error = vi.fn();
        public readonly warn = vi.fn();
        public readonly debug = vi.fn();
        public readonly verbose = vi.fn();
      },
    ),
  };
});
