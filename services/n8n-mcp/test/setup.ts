import { vi } from 'vitest';

vi.mock('@opentelemetry/api', () => ({
  context: {
    active: () => ({}),
  },
  trace: {
    getSpanContext: () => undefined,
  },
}));
