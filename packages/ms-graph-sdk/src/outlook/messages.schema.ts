import z from 'zod/v4';
import { ItemBody, isoDatetimeToDate, Recipient } from '../shared/primitives';

/**
 * Indicates the follow-up status of an item for the user to follow up on later.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/followupflag?view=graph-rest-1.0
 */
export const FollowupFlag = z.object({
  flagStatus: z.enum(['notFlagged', 'complete', 'flagged']).optional(),
  dueDateTime: z.object({ dateTime: z.string(), timeZone: z.string() }).optional(),
  startDateTime: z.object({ dateTime: z.string(), timeZone: z.string() }).optional(),
  completedDateTime: z.object({ dateTime: z.string(), timeZone: z.string() }).optional(),
});

/**
 * A message in a mailbox folder.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0
 */
export const Message = z.object({
  id: z.string(),
  subject: z.string().optional(),
  bodyPreview: z.string().optional(),
  body: ItemBody.optional().nullable(),
  uniqueBody: ItemBody.optional().nullable(),
  from: Recipient.optional().nullable(),
  sender: Recipient.optional().nullable(),
  toRecipients: z.array(Recipient).optional(),
  ccRecipients: z.array(Recipient).optional(),
  bccRecipients: z.array(Recipient).optional(),
  replyTo: z.array(Recipient).optional(),
  conversationId: z.string().optional(),
  internetMessageId: z.string().optional(),
  internetMessageHeaders: z.array(z.object({ name: z.string(), value: z.string() })).optional(),
  parentFolderId: z.string().optional(),
  receivedDateTime: isoDatetimeToDate({ offset: true }).optional(),
  sentDateTime: isoDatetimeToDate({ offset: true }).optional(),
  createdDateTime: isoDatetimeToDate({ offset: true }).optional(),
  lastModifiedDateTime: isoDatetimeToDate({ offset: true }).optional(),
  isRead: z.boolean().optional().nullable(),
  isDraft: z.boolean().optional().nullable(),
  hasAttachments: z.boolean().optional(),
  importance: z.enum(['low', 'normal', 'high']).optional(),
  inferenceClassification: z.enum(['focused', 'other']).optional(),
  categories: z.array(z.string()).optional(),
  flag: FollowupFlag.optional(),
  webLink: z.string().optional(),
  isDeliveryReceiptRequested: z.boolean().optional().nullable(),
  isReadReceiptRequested: z.boolean().optional().nullable(),
});

export type Message = z.infer<typeof Message>;
