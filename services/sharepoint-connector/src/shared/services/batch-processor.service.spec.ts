import { Logger } from '@nestjs/common';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BatchProcessorService } from './batch-processor.service';

describe('BatchProcessorService', () => {
  let service: BatchProcessorService;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(BatchProcessorService).compile();
    service = unit;
  });

  describe('processInBatches', () => {
    it('processes items in correct batch sizes', async () => {
      const items = [1, 2, 3, 4, 5, 6, 7];
      const batchSize = 3;

      const mockLogger = {
        debug: vi.fn(),
        error: vi.fn(),
        log: vi.fn(),
        warn: vi.fn(),
        verbose: vi.fn(),
        fatal: vi.fn(),
        setLogLevels: vi.fn(),
        setContext: vi.fn(),
      } as unknown as Logger;

      const result = await service.processInBatches({
        items,
        batchSize,
        processor: async (batch) => {
          processedBatches.push([...batch]);
          return batch.map((n) => n * 2);
        },
        logger: mockLogger,
      });

      expect(processedBatches).toEqual([[1, 2, 3], [4, 5, 6], [7]]);
      expect(result).toEqual([2, 4, 6, 8, 10, 12, 14]);
    });

    it('handles empty input array', async () => {
      const mockLogger = {
        debug: vi.fn(),
        error: vi.fn(),
        log: vi.fn(),
        warn: vi.fn(),
        verbose: vi.fn(),
        fatal: vi.fn(),
        setLogLevels: vi.fn(),
        setContext: vi.fn(),
      } as unknown as Logger;

      const result = await service.processInBatches({
        items: [],
        batchSize: 5,
        processor: async () => [],
        logger: mockLogger,
      });

      expect(result).toEqual([]);
    });

    it('validates input parameters', async () => {
      const mockLogger = {
        debug: vi.fn(),
        error: vi.fn(),
        log: vi.fn(),
        warn: vi.fn(),
        verbose: vi.fn(),
        fatal: vi.fn(),
        setLogLevels: vi.fn(),
        setContext: vi.fn(),
      } as unknown as Logger;

      await expect(
        service.processInBatches({
          items: null as unknown as number[],
          batchSize: 5,
          processor: async () => [],
          logger: mockLogger,
        }),
      ).rejects.toThrow('items must be an array');

      await expect(
        service.processInBatches({
          items: [1, 2, 3],
          batchSize: 0,
          processor: async () => [],
          logger: mockLogger,
        }),
      ).rejects.toThrow('batchSize must be a positive integer');

      await expect(
        service.processInBatches({
          items: [1, 2, 3],
          batchSize: -1,
          processor: async () => [],
          logger: mockLogger,
        }),
      ).rejects.toThrow('batchSize must be a positive integer');
    });
  });
});
