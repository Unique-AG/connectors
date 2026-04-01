import z from 'zod/v4';

export const FullSyncEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.retrigger'),
  payload: z.object({ userProfileId: z.string() }),
});
