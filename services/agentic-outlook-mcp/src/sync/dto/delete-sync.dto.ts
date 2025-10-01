import { createZodDto } from 'nestjs-zod';
import * as z from 'zod';

export const deleteSyncSchema = z.object({
  wipeData: z.boolean().optional(),
});

export class DeleteSyncDto extends createZodDto(deleteSyncSchema) {}