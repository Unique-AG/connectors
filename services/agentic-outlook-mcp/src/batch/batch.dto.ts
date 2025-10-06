import { createZodDto } from 'nestjs-zod';
import * as z from 'zod';

export const batchOperationSchema = z.enum(['PUT', 'PATCH', 'DELETE']);
export type BatchOperation = z.infer<typeof batchOperationSchema>;

export const batchTableSchema = z.enum(['user_profiles', 'folders', 'emails']);
export type BatchTable = z.infer<typeof batchTableSchema>;

const batchSchema = z.object({
  clientId: z.string(),
  data: z.array(
    z.object({
      op_id: z.number(),
      op: batchOperationSchema,
      type: batchTableSchema,
      id: z.string(),
      tx_id: z.number().optional(),
      data: z.record(z.string(), z.any()).optional(),
      old: z.record(z.string(), z.any()).optional(),
      metadata: z.string().optional(),
    }),
  ),
});

export class BatchDto extends createZodDto(batchSchema) {}
