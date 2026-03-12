import z from 'zod/v4';

const FullSyncExecuteEvent = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.execute'),
  payload: z.object({ userProfileId: z.string(), version: z.string() }),
});

const FullSyncRecoveryEvent = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.recovery-requested'),
  payload: z.object({ userProfileId: z.string() }),
});

export const FullSyncEventDto = z.discriminatedUnion('type', [
  FullSyncExecuteEvent,
  FullSyncRecoveryEvent,
]);
