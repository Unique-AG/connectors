import { vi } from 'vitest';

process.env.NODE_ENV ??= 'test';
process.env.LOG_LEVEL ??= 'warn';
process.env.PORT ??= '0';
process.env.KYCKR_API_KEY ??= 'test-api-key';
process.env.KYCKR_API_BASE_URL ??= 'https://test-api.kyckr.com/v2';
process.env.MCP_API_KEY ??= 'test-kyckr-mcp-key';

vi.mock('@nestjs/common', async () => {
  const actual = await vi.importActual('@nestjs/common');
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
