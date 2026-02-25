import z from 'zod/v4';

const SubscriptionMessageChanged = z.object({
  type: z.literal('unique.outlook-semantic-mcp.mail-event.live-change-notification-received'),
  payload: z.object({ subscriptionId: z.string(), messageId: z.string() }),
});

const FullSyncMessageChanged = z.object({
  type: z.literal('unique.outlook-semantic-mcp.mail-event.full-sync-change-notification-scheduled'),
  payload: z.object({
    userProfileId: z.string(),
    messageId: z.string(),
  }),
});

export const MessageEventDto = z.discriminatedUnion('type', [
  SubscriptionMessageChanged,
  FullSyncMessageChanged,
]);
