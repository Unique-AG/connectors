import z from 'zod';

const SubscriptionMessageChanged = z.object({
  type: z.literal('unique.outlook-semantic-mcp.mail.subscription-message-changed'),
  payload: z.object({ subscriptionId: z.string(), messageId: z.string() }),
});

const FullSyncNewMessage = z.object({
  type: z.literal('unique.outlook-semantic-mcp.mail.new-message'),
  payload: z.object({
    userProfileId: z.string(),
    messageId: z.string(),
  }),
});

const FullSyncMessageMetadataChanged = z.object({
  type: z.literal('unique.outlook-semantic-mcp.mail.message-metadata-changed'),
  payload: z.object({
    userProfileId: z.string(),
    messageId: z.string(),
    key: z.string(),
  }),
});

export const MessageEventDto = z.discriminatedUnion('type', [
  SubscriptionMessageChanged,
  FullSyncNewMessage,
  FullSyncMessageMetadataChanged,
]);
