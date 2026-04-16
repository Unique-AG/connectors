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
  createdDateTime: z.string(),
  categories: z.array(z.string()).optional().nullable().nullish(),
  ccRecipients: z.array(graphRecipientSchema).optional().nullable().nullish(),
  conversationId: z.string().optional().nullable().nullish(),
  flag: graphFollowupFlagSchema.optional().nullable(),
  from: graphRecipientSchema.optional().nullable(),
  hasAttachments: z.boolean().optional().nullable(),
  id: z.string(),
  importance: z.enum(['low', 'normal', 'high']).optional().nullable(),
  inferenceClassification: z.enum(['focused', 'other']).optional().nullable(),
  webLink: z.string(),
  internetMessageId: z.string().optional().nullable(),
  isDraft: z.boolean().optional().nullable(),
  isRead: z.boolean().optional().nullable(),
  lastModifiedDateTime: z.string(),
  parentFolderId: z.string(),
  receivedDateTime: z.string(),
  sender: graphRecipientSchema.optional().nullable(),
  sentDateTime: z.string().optional().nullable(),
  subject: z.string().optional().nullable(),
  toRecipients: z.array(graphRecipientSchema).optional().nullable(),
  uniqueBody: graphItemBodySchema.optional().nullable(),
});

export type GraphMessage = z.infer<typeof graphMessageSchema>;

export const GraphMessageFields = asAllOptions<keyof GraphMessage>()([
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
  `internetMessageId`,
  `isDraft`,
  `isRead`,
  `lastModifiedDateTime`,
  `parentFolderId`,
  `receivedDateTime`,
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
