import { DiscoveryService } from '@nestjs/core';
import { TypeID } from 'typeid-js';
import * as z from 'zod';
import { batchOperationSchema, batchTableSchema } from './batch.dto';

export const batchProcessorOptionsSchema = z.object({
  table: batchTableSchema,
  operation: batchOperationSchema,
  schema: z.instanceof(z.ZodType).optional(),
});

export const batchProcessorHandlerSchema = z.function({
  input: [
    z.instanceof(TypeID<'user_profile'>),
    z.string(),
    z.union([z.record(z.string(), z.unknown()), z.instanceof(z.ZodType)]).optional(),
  ],
  output: z.promise(z.void()),
});

export type BatchProcessorHandler = z.infer<typeof batchProcessorHandlerSchema>;
export type BatchProcessorOptions = z.infer<typeof batchProcessorOptionsSchema>;

export const BatchProcessor = DiscoveryService.createDecorator<BatchProcessorOptions>();
