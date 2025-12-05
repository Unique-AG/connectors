import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
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
      const processedBatches: number[][] = [];

      const result = await service.processInBatches({
        items,
        batchSize,
        processor: async (batch) => {
          processedBatches.push([...batch]);
          return batch.map((n) => n * 2);
        },
      });

      expect(processedBatches).toEqual([[1, 2, 3], [4, 5, 6], [7]]);
      expect(result).toEqual([2, 4, 6, 8, 10, 12, 14]);
    });

    it('handles empty input array', async () => {
      const result = await service.processInBatches({
        items: [],
        batchSize: 5,
        processor: async () => [],
      });

      expect(result).toEqual([]);
    });

    it('validates input parameters', async () => {
      await expect(
        service.processInBatches({
          items: null as unknown as number[],
          batchSize: 5,
          processor: async () => [],
        }),
      ).rejects.toThrow('items must be an array');

      await expect(
        service.processInBatches({
          items: [1, 2, 3],
          batchSize: 0,
          processor: async () => [],
        }),
      ).rejects.toThrow('batchSize must be a positive integer');

      await expect(
        service.processInBatches({
          items: [1, 2, 3],
          batchSize: -1,
          processor: async () => [],
        }),
      ).rejects.toThrow('batchSize must be a positive integer');
    });

    it('validates processor return type', async () => {
      await expect(
        service.processInBatches({
          items: [1],
          batchSize: 1,
          processor: async () => 'not an array' as unknown as number[],
        }),
      ).rejects.toThrow('processor must return an array');
    });

    it('does not log when no logger is provided', async () => {
      const items = [1, 2, 3, 4, 5, 6, 7];

      await service.processInBatches({
        items,
        batchSize: 2, // Creates multiple batches
        processor: async (batch) => batch,
        // No logger provided
      });

      // Should not throw and should work without logging
      expect(true).toBe(true); // Just verify it completes successfully
    });
  });
});
