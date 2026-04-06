import z from 'zod/v4';

export const LiveCatchUpExecutEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.live-catch-up.execute'),
  payload: z.object({ subscriptionId: z.string() }),
});

export const LiveCatchUpReadyRecheckEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.live-catch-up.ready-recheck'),
  payload: z.object({ subscriptionId: z.string() }),
});

export const LiveCatchUpEventDto = z.discriminatedUnion('type', [
  LiveCatchUpExecutEventDto,
  LiveCatchUpReadyRecheckEventDto,
]);
