import { vi } from 'vitest';

process.env.NODE_ENV ??= 'test';
process.env.LOG_LEVEL ??= 'warn';
process.env.PORT ??= '0';
process.env.APP_BUFFER_LOGS ??= 'disabled';
process.env.TEMENOS_API_KEY ??= 'test-api-key';
process.env.TEMENOS_API_BASE_URL ??= 'https://api.example.com';
process.env.MCP_API_KEY ??= 'test-temenos-mcp-key';

vi.mock('@nestjs/common', async () => {
  const actual = await vi.importActual('@nestjs/common');
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => ({
      log: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
      verbose: vi.fn(),
    })),
  };
});
