import z from 'zod/v4';
import { asAllOptions } from '~/utils/as-all-options';

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
  bccRecipients: z.array(graphRecipientSchema).optional(),
  body: graphItemBodySchema.optional().nullable(),
  bodyPreview: z.string().optional(),
  categories: z.array(z.string()).optional(),
  ccRecipients: z.array(graphRecipientSchema).optional(),
  conversationId: z.string().optional(),
  createdDateTime: z.string(),
  flag: graphFollowupFlagSchema.optional().nullable(),
  from: graphRecipientSchema.optional().nullable(),
  hasAttachments: z.boolean().optional(),
  id: z.string(),
  importance: z.enum(['low', 'normal', 'high']).optional(),
  inferenceClassification: z.enum(['focused', 'other']).optional(),
  internetMessageHeaders: z
    .array(
      z.object({
        name: z.string(),
        value: z.string(),
      }),
    )
    .optional(),
  webLink: z.string(),
  internetMessageId: z.string().optional(),
  isDeliveryReceiptRequested: z.boolean().optional(),
  isDraft: z.boolean().optional(),
  isRead: z.boolean().optional(),
  isReadReceiptRequested: z.boolean().optional(),
  lastModifiedDateTime: z.string(),
  parentFolderId: z.string(),
  receivedDateTime: z.string(),
  replyTo: z.array(graphRecipientSchema).optional(),
  sender: graphRecipientSchema.optional().nullable(),
  sentDateTime: z.string().optional(),
  subject: z.string().optional(),
  toRecipients: z.array(graphRecipientSchema).optional(),
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
