import z from 'zod/v4';

export const FullSyncRecoveryEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.recovery-requested'),
  payload: z.object({ userProfileId: z.string() }),
});
