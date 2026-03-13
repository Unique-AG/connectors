import { asAllOptions } from '@unique-ag/utils';
import z from 'zod/v4';

const graphEmailAddressSchema = z.object({
  address: z.string().optional(),
  name: z.string().optional(),
});

const graphRecipientSchema = z.object({
  emailAddress: graphEmailAddressSchema.optional(),
});

const graphItemBodySchema = z.object({
  contentType: z.enum(['text', 'html']).optional(),
  content: z.string().optional(),
});

const graphDateTimeTimeZoneSchema = z.object({
  dateTime: z.string(),
  timeZone: z.string(),
});

const graphFollowupFlagSchema = z.object({
  completedDateTime: graphDateTimeTimeZoneSchema.optional().nullable(),
  dueDateTime: graphDateTimeTimeZoneSchema.optional().nullable(),
  flagStatus: z.enum(['notFlagged', 'complete', 'flagged']).optional(),
  startDateTime: graphDateTimeTimeZoneSchema.optional().nullable(),
});

export const graphMessageSchema = z.object({
  bccRecipients: z.array(graphRecipientSchema).optional().nullable(),
  body: graphItemBodySchema.optional().nullable(),
  bodyPreview: z.string().optional().nullable(),
  categories: z.array(z.string()).optional().nullable(),
  ccRecipients: z.array(graphRecipientSchema).optional().nullable(),
  conversationId: z.string().optional().nullable(),
  createdDateTime: z.string(),
  flag: graphFollowupFlagSchema.optional().nullable(),
  from: graphRecipientSchema.optional().nullable(),
  hasAttachments: z.boolean().optional().nullable(),
  id: z.string(),
  importance: z.enum(['low', 'normal', 'high']).optional().nullable(),
  inferenceClassification: z.enum(['focused', 'other']).optional().nullable(),
  internetMessageHeaders: z
    .array(
      z.object({
        name: z.string(),
        value: z.string(),
      }),
    )
    .optional()
    .nullable(),
  webLink: z.string(),
  internetMessageId: z.string().optional().nullable(),
  isDeliveryReceiptRequested: z.boolean().optional().nullable(),
  isDraft: z.boolean().optional().nullable(),
  isRead: z.boolean().optional().nullable(),
  isReadReceiptRequested: z.boolean().optional().nullable(),
  lastModifiedDateTime: z.string(),
  parentFolderId: z.string(),
  receivedDateTime: z.string(),
  replyTo: z.array(graphRecipientSchema).optional().nullable(),
  sender: graphRecipientSchema.optional().nullable(),
  sentDateTime: z.string().optional().nullable(),
  subject: z.string().optional().nullable(),
  toRecipients: z.array(graphRecipientSchema).optional().nullable(),
  uniqueBody: graphItemBodySchema.optional().nullable(),
});

export type GraphMessage = z.infer<typeof graphMessageSchema>;

export const GraphMessageFields = asAllOptions<keyof GraphMessage>()([
  `bccRecipients`,
  `body`,
  `bodyPreview`,
  `categories`,
  `ccRecipients`,
  `conversationId`,
  `createdDateTime`,
  `flag`,
  `from`,
  `hasAttachments`,
  `id`,
  `importance`,
  `inferenceClassification`,
  `internetMessageHeaders`,
  `internetMessageId`,
  `isDeliveryReceiptRequested`,
  `isDraft`,
  `isRead`,
  `isReadReceiptRequested`,
  `lastModifiedDateTime`,
  `parentFolderId`,
  `receivedDateTime`,
  `replyTo`,
  `sender`,
  `sentDateTime`,
  `subject`,
  `toRecipients`,
  `uniqueBody`,
  `webLink`,
]);

export const graphMessagesResponseSchema = z.object({
  '@odata.context': z.string().optional(),
  value: z.array(graphMessageSchema),
  '@odata.nextLink': z.string().optional(),
});

export type GraphMessagesResponse = z.infer<typeof graphMessagesResponseSchema>;

const fileDiffGraphMessage = graphMessageSchema.pick({
  internetMessageId: true,
  id: true,
  uniqueBody: true,
  toRecipients: true,
  sentDateTime: true,
  from: true,
  subject: true,
  lastModifiedDateTime: true,
  webLink: true,
});

export type FileDiffGraphMessage = z.infer<typeof fileDiffGraphMessage>;

export const FileDiffGraphMessageFields = asAllOptions<keyof FileDiffGraphMessage>()([
  `internetMessageId`,
  `id`,
  `uniqueBody`,
  `toRecipients`,
  `sentDateTime`,
  `from`,
  `subject`,
  `lastModifiedDateTime`,
  `webLink`,
]);

export const fileDiffGraphMessageResponseSchema = z.object({
  '@odata.context': z.string().optional(),
  value: z.array(fileDiffGraphMessage),
  '@odata.nextLink': z.string().optional(),
});

const fullSyncGraphMessage = graphMessageSchema.pick({
  id: true,
  internetMessageId: true,
  createdDateTime: true,
  lastModifiedDateTime: true,
  from: true,
  subject: true,
  uniqueBody: true,
});

export type FullSyncGraphMessage = z.infer<typeof fullSyncGraphMessage>;

export const FullSyncGraphMessageFields = asAllOptions<keyof FullSyncGraphMessage>()([
  `id`,
  `internetMessageId`,
  `createdDateTime`,
  `lastModifiedDateTime`,
  `from`,
  `subject`,
  `uniqueBody`,
]);

export const fullSyncGraphMessageResponseSchema = z.object({
  '@odata.context': z.string().optional(),
  value: z.array(fullSyncGraphMessage),
  '@odata.nextLink': z.string().optional(),
});
