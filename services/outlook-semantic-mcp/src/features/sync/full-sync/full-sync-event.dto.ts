import z from 'zod/v4';

const FullSyncRecoveryRequestedEvent = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.recovery-requested'),
  payload: z.object({ userProfileId: z.string() }),
});

const FullSyncRetriggerEvent = z.object({
  type: z.literal('unique.outlook-semantic-mcp.full-sync.retrigger'),
  payload: z.object({ userProfileId: z.string() }),
});

export const FullSyncEventDto = z.discriminatedUnion('type', [
  FullSyncRecoveryRequestedEvent,
  FullSyncRetriggerEvent,
]);
