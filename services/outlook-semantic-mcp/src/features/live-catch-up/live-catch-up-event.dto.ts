import z from 'zod/v4';

const LiveCatchUpExecuteEvent = z.object({
  type: z.literal('unique.outlook-semantic-mcp.live-catch-up.execute'),
  payload: z.object({ subscriptionId: z.string(), messageIds: z.array(z.string()) }),
});

export const LiveCatchUpEventDto = z.discriminatedUnion('type', [LiveCatchUpExecuteEvent]);
