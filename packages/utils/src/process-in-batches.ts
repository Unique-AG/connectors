import assert from 'node:assert';
import { chunk } from 'remeda';
import { sanitizeError } from './normalize-error';

export interface BatchProcessorOptions<TInput, TOutput> {
  items: TInput[];
  batchSize: number;
  processor: (batch: TInput[], batchIndex: number) => Promise<TOutput[]>;
  logger: { debug: (msg: string) => void; error: (obj: object) => void };
  logPrefix?: string;
}

export async function processInBatches<TInput, TOutput>({
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
