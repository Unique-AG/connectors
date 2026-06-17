import { describe, expect, it } from 'vitest';
import {
  CRON_EVERY_15_MINUTES,
  DEFAULT_PROCESSING_CONCURRENCY,
} from '../../constants/defaults.constants';
import { ProcessingConfigSchema } from '../processing.schema';

describe('ProcessingConfigSchema', () => {
  describe('defaults', () => {
    it('applies default concurrency when not provided', () => {
      const result = ProcessingConfigSchema.parse({});

      expect(result.concurrency).toBe(DEFAULT_PROCESSING_CONCURRENCY);
    });

    it('applies default scan interval cron when not provided', () => {
      const result = ProcessingConfigSchema.parse({});

      expect(result.scanIntervalCron).toBe(CRON_EVERY_15_MINUTES);
    });

    it('leaves maxItemsToScan undefined when not provided', () => {
      const result = ProcessingConfigSchema.parse({});

      expect(result.maxItemsToScan).toBeUndefined();
    });
  });

  describe('explicit values', () => {
    it('accepts a custom concurrency value', () => {
      const result = ProcessingConfigSchema.parse({ concurrency: 4 });

      expect(result.concurrency).toBe(4);
    });

    it('coerces string concurrency to a number', () => {
      const result = ProcessingConfigSchema.parse({ concurrency: '3' });

      expect(result.concurrency).toBe(3);
    });

    it('accepts a custom cron expression', () => {
      const result = ProcessingConfigSchema.parse({ scanIntervalCron: '0 * * * *' });

      expect(result.scanIntervalCron).toBe('0 * * * *');
    });

    it('accepts a numeric maxItemsToScan', () => {
      const result = ProcessingConfigSchema.parse({ maxItemsToScan: 100 });

      expect(result.maxItemsToScan).toBe(100);
    });

    it('treats empty string maxItemsToScan as undefined', () => {
      const result = ProcessingConfigSchema.parse({ maxItemsToScan: '' });

      expect(result.maxItemsToScan).toBeUndefined();
    });
  });

  describe('validation failures', () => {
    it('rejects zero concurrency', () => {
      expect(() => ProcessingConfigSchema.parse({ concurrency: 0 })).toThrow();
    });

    it('rejects negative concurrency', () => {
      expect(() => ProcessingConfigSchema.parse({ concurrency: -1 })).toThrow();
    });

    it('rejects non-positive maxItemsToScan', () => {
      expect(() => ProcessingConfigSchema.parse({ maxItemsToScan: 0 })).toThrow();
    });
  });
});
