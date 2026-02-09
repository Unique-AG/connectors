import z from 'zod/v4';

export const GraphEmailImportance = z.enum(['low', 'normal', 'high']);
export type GraphEmailImportance = z.infer<typeof GraphEmailImportance>;

export const GraphEmailAddress = z.object({
  name: z.string().optional(),
  address: z.string(),
});
export type GraphEmailAddress = z.infer<typeof GraphEmailAddress>;

export const GraphRecipient = z.object({
  emailAddress: GraphEmailAddress,
});
export type GraphRecipient = z.infer<typeof GraphRecipient>;

export const GraphEmail = z.object({
  id: z.string(),
  subject: z.string().nullable(),
  from: GraphRecipient.nullable(),
  toRecipients: z.array(GraphRecipient),
  ccRecipients: z.array(GraphRecipient),
  receivedDateTime: z.string().nullable(),
  parentFolderId: z.string(),
  conversationId: z.string().nullable(),
  conversationIndex: z.string().nullable(),
  hasAttachments: z.boolean(),
  isDraft: z.boolean(),
  importance: GraphEmailImportance,
});
export type GraphEmail = z.infer<typeof GraphEmail>;

export const GraphMailFolder = z.object({
  id: z.string(),
});
export type GraphMailFolder = z.infer<typeof GraphMailFolder>;

export const GRAPH_EMAIL_SELECT_FIELDS = [
  'id',
  'subject',
  'from',
  'toRecipients',
  'ccRecipients',
  'receivedDateTime',
  'parentFolderId',
  'conversationId',
  'conversationIndex',
  'hasAttachments',
  'isDraft',
  'importance',
].join(',');
