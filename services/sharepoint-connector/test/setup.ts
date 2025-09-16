import { vi } from 'vitest';

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

// Silence pino logs during tests
vi.mock('nestjs-pino', async () => {
  const actual = await vi.importActual('nestjs-pino');
  return {
    ...actual,
    LoggerModule: { forRootAsync: () => ({}) },
    Logger: vi.fn().mockImplementation(() => ({
      log: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
      verbose: vi.fn(),
    })),
  };
});
