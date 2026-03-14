import { vi } from 'vitest';

vi.mock('nestjs-otel', () => ({
  Span: () => (_target: unknown, _key: string, descriptor: PropertyDescriptor) => descriptor,
  TraceService: vi.fn().mockImplementation(() => ({
    getSpan: vi.fn().mockReturnValue({
      setAttribute: vi.fn(),
      addEvent: vi.fn(),
    }),
  })),
  MetricService: vi.fn().mockImplementation(() => ({
    getCounter: vi.fn().mockReturnValue({ add: vi.fn() }),
    getHistogram: vi.fn().mockReturnValue({ record: vi.fn() }),
  })),
  OpenTelemetryModule: {
    forRoot: vi.fn().mockReturnValue({ module: class {} }),
  },
}));
