import z from 'zod/v4';

const FullSyncRecoveryEvent = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.recovery'),
  payload: z.object({ userProfileId: z.string() }),
});

export const FullSyncEventDto = z.discriminatedUnion('type', [FullSyncRecoveryEvent]);
