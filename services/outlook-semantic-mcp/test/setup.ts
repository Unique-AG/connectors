import { vi } from 'vitest';

// Required at startup. Code that reads the features when its file loads needs them before any import.
process.env.MCP_BACKEND ??= 'microsoft_graph_and_unique_api';
process.env.DELEGATED_ACCESS_SCAN ??= 'full_access_only';

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
