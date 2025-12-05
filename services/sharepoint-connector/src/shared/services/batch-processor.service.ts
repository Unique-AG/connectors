import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { chunk } from 'remeda';
import { sanitizeError } from '../../utils/normalize-error';

export interface BatchProcessorOptions<TInput, TOutput> {
  /** Array of items to process in batches */
  items: TInput[];
  /** Maximum number of items per batch */
  batchSize: number;
  /** Function to process each batch, returns results for that batch */
  processor: (batch: TInput[], batchIndex: number) => Promise<TOutput[]>;
  /** Logger for progress tracking and error reporting */
  logger: Logger;
  logPrefix?: string;
}

@Injectable()
export class BatchProcessorService {
  public async processInBatches<TInput, TOutput>({
    items,
    batchSize,
    processor,
    logger,
    logPrefix = '',
  }: BatchProcessorOptions<TInput, TOutput>): Promise<TOutput[]> {
    assert(Array.isArray(items), 'items must be an array');
    assert(Number.isInteger(batchSize) && batchSize > 0, 'batchSize must be a positive integer');

    const chunks = chunk(items, batchSize);
    const allResults: TOutput[] = [];

    const shouldLogProgress = chunks.length > 1;
    if (shouldLogProgress) {
      logger.debug(`${logPrefix} Processing ${items.length} items in ${chunks.length} chunks`);
    }

    // Process each chunk sequentially to maintain order and avoid overwhelming external services
    for (const [index, batch] of chunks.entries()) {
      if (shouldLogProgress) {
        logger.debug(
          `${logPrefix} Processing chunk ${index + 1}/${chunks.length} (${batch.length} items)`,
        );
      }

      try {
        const results = await processor(batch, index);
        allResults.push(...results);
      } catch (error) {
        logger.error({
          msg: `${logPrefix} Failed to process batch ${index + 1}`,
          batchIndex: index,
          batchSize: batch.length,
          error: sanitizeError(error),
        });
        throw error;
      }
    }

    return allResults;
  }
}
