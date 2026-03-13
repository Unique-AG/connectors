import z from 'zod/v4';
import { ODataQueryParamsSchema } from '../shared/odata';
import { Recipient } from '../shared/primitives';
import { FileAttachment } from './file-attachment.schema';

/**
 * Parameters for listing mail folders under the root folder of the signed-in user.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0
 */
const ListMailFoldersRequest = ODataQueryParamsSchema.extend({
  immutableIds: z
    .boolean()
    .optional()
    .describe('When true, requests immutable IDs in the response.'),
});
export type ListMailFoldersRequest = z.input<typeof ListMailFoldersRequest>;

/**
 * Parameters for retrieving a single mail folder by ID.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/mailfolder-get?view=graph-rest-1.0
 */
const GetMailFolderRequest = z.object({
  folderId: z.string().describe('The mail folder ID to retrieve.'),
  expand: z.string().optional().describe('OData $expand clause to include related entities.'),
  immutableIds: z
    .boolean()
    .optional()
    .describe('When true, requests immutable IDs in the response.'),
});
export type GetMailFolderRequest = z.infer<typeof GetMailFolderRequest>;

/**
 * Parameters for retrieving a mail folder by its well-known name (e.g. inbox, drafts, sentitems).
 *
 * @see https://learn.microsoft.com/en-us/graph/api/mailfolder-get?view=graph-rest-1.0
 */
const GetSystemFolderRequest = z.object({
  folderName: z
    .string()
    .describe('The well-known folder name (e.g. inbox, drafts, sentitems, deleteditems).'),
  immutableIds: z
    .boolean()
    .optional()
    .describe('When true, requests immutable IDs in the response.'),
});
export type GetSystemFolderRequest = z.infer<typeof GetSystemFolderRequest>;

/**
 * Parameters for retrieving incremental changes to mail folders using delta query.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/mailfolder-delta?view=graph-rest-1.0
 */
const GetMailFoldersDeltaRequest = z.object({
  deltaLink: z
    .string()
    .optional()
    .describe('The delta link from a previous delta response to resume change tracking.'),
  immutableIds: z
    .boolean()
    .optional()
    .describe('When true, requests immutable IDs in the response.'),
});
export type GetMailFoldersDeltaRequest = z.infer<typeof GetMailFoldersDeltaRequest>;

/**
 * Parameters for retrieving a single message by ID.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
 */
const GetMessageRequest = z.object({
  messageId: z.string().describe('The message ID to retrieve.'),
  select: z.array(z.string()).optional().describe('OData $select properties to return.'),
  immutableIds: z
    .boolean()
    .optional()
    .describe('When true, requests immutable IDs in the response.'),
});
export type GetMessageRequest = z.infer<typeof GetMessageRequest>;

/**
 * Parameters for listing messages in the signed-in user's mailbox.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
 */
const ListMessagesRequest = ODataQueryParamsSchema.extend({
  immutableIds: z
    .boolean()
    .optional()
    .describe('When true, requests immutable IDs in the response.'),
});
export type ListMessagesRequest = z.input<typeof ListMessagesRequest>;

/**
 * Request body for creating a draft message in the signed-in user's Drafts folder.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/user-post-messages?view=graph-rest-1.0
 */
export const CreateMessageRequest = z.object({
  subject: z.string().describe('The subject of the message.'),
  body: z
    .object({
      contentType: z
        .enum(['HTML', 'Text'])
        .describe('The type of the content. Possible values are text and html.'),
      content: z.string().describe('The content of the item body.'),
    })
    .describe('The body of the message. It can be in HTML or text format.'),
  toRecipients: z.array(Recipient).describe('The To: recipients for the message.'),
  ccRecipients: z.array(Recipient).optional().describe('The Cc: recipients for the message.'),
  attachments: z.array(FileAttachment).optional().describe('The file attachments for the message.'),
});
export type CreateMessageRequest = z.infer<typeof CreateMessageRequest>;
