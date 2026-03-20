import z from 'zod/v4';

export const MessageEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.mail-event.live-change-notification-received'),
  payload: z.object({ subscriptionId: z.string(), messageId: z.string() }),
});
