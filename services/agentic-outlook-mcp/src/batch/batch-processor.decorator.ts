import { DiscoveryService } from '@nestjs/core';
import * as z from 'zod';
import { batchOperationSchema, batchTableSchema } from './batch.dto';

export const batchProcessorOptionsSchema = z.object({
  table: batchTableSchema,
  operation: batchOperationSchema,
});

export type BatchProcessorOptions = z.infer<typeof batchProcessorOptionsSchema>;

export const BatchProcessor = DiscoveryService.createDecorator<BatchProcessorOptions>();
