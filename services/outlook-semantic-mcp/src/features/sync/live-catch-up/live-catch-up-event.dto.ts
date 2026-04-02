import z from 'zod/v4';

export const LiveCatchUpEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.live-catch-up.execute'),
  payload: z.object({ subscriptionId: z.string() }),
});
