import { createZodDto } from 'nestjs-zod';
import * as z from 'zod';

export const syncStatusSchema = z.object({
  syncActivatedAt: z.iso.datetime().nullable(),
  syncDeactivatedAt: z.iso.datetime().nullable(),
  syncLastSyncedAt: z.iso.datetime().nullable(),
});

export class SyncStatusDto extends createZodDto(syncStatusSchema) {}

