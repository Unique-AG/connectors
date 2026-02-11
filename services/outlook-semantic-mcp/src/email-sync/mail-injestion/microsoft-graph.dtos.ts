import z from "zod/v4";
import { asAllOptions } from "~/utils/all-options";

const graphEmailAddressSchema = z.object({
  address: z.string().optional(),
  name: z.string().optional(),
});

const graphRecipientSchema = z.object({
  emailAddress: graphEmailAddressSchema,
});

const graphItemBodySchema = z.object({
  contentType: z.enum(["text", "html"]).optional(),
});

const graphDateTimeTimeZoneSchema = z.object({
  dateTime: z.string(),
  timeZone: z.string(),
});

const graphFollowupFlagSchema = z.object({
  completedDateTime: graphDateTimeTimeZoneSchema.optional().nullable(),
  dueDateTime: graphDateTimeTimeZoneSchema.optional().nullable(),
  flagStatus: z.enum(["notFlagged", "complete", "flagged"]).optional(),
  startDateTime: graphDateTimeTimeZoneSchema.optional().nullable(),
});

export const graphMessageSchema = z.object({
  bccRecipients: z.array(graphRecipientSchema),
  body: graphItemBodySchema.nullable(),
  bodyPreview: z.string(),
  categories: z.array(z.string()),
  ccRecipients: z.array(graphRecipientSchema),
  conversationId: z.string(),
  createdDateTime: z.string(),
  flag: graphFollowupFlagSchema.nullable(),
  from: graphRecipientSchema.nullable(),
  hasAttachments: z.boolean(),
  id: z.string(),
  importance: z.enum(["low", "normal", "high"]),
  inferenceClassification: z.enum(["focused", "other"]),
  internetMessageHeaders: z.array(
    z.object({
      name: z.string(),
      value: z.string(),
    }),
  ),
  internetMessageId: z.string(),
  isDeliveryReceiptRequested: z.boolean(),
  isDraft: z.boolean(),
  isRead: z.boolean(),
  isReadReceiptRequested: z.boolean(),
  lastModifiedDateTime: z.string(),
  parentFolderId: z.string(),
  receivedDateTime: z.string(),
  replyTo: z.array(graphRecipientSchema),
  sender: graphRecipientSchema.nullable(),
  sentDateTime: z.string(),
  subject: z.string(),
  toRecipients: z.array(graphRecipientSchema),
  uniqueBody: graphItemBodySchema.nullable(),
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
]);

export const graphMessagesResponseSchema = z.object({
  "@odata.context": z.string(),
  value: z.array(graphMessageSchema),
  "@odata.nextLink": z.string().optional(),
});

export type GraphMessagesResponse = z.infer<typeof graphMessagesResponseSchema>;
