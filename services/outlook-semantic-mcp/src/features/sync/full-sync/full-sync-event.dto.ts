import z from 'zod/v4';

export const FullSyncEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.sync.full-sync'),
  payload: z.object({ userProfileId: z.string() }),
});
