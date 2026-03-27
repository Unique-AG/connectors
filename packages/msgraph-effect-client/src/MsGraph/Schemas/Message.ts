import { Schema } from "effect";

import { RecipientSchema } from "./Common.js";

export const BodySchema = Schema.Struct({
  contentType: Schema.Literal("text", "html"),
  content: Schema.String,
});

export type Body = Schema.Schema.Type<typeof BodySchema>;

export const MailFolderSchema = Schema.Struct({
  id: Schema.String,
  displayName: Schema.String,
  parentFolderId: Schema.NullOr(Schema.String),
  childFolderCount: Schema.Number,
  unreadItemCount: Schema.Number,
  totalItemCount: Schema.Number,
  isHidden: Schema.optional(Schema.Boolean),
  sizeInBytes: Schema.optional(Schema.Number),
});

export type MailFolder = Schema.Schema.Type<typeof MailFolderSchema>;

export const AttachmentSchema = Schema.Struct({
  id: Schema.String,
  name: Schema.String,
  contentType: Schema.String,
  size: Schema.Number,
  isInline: Schema.Boolean,
  contentId: Schema.NullOr(Schema.String),
  lastModifiedDateTime: Schema.optional(Schema.String),
});

export type Attachment = Schema.Schema.Type<typeof AttachmentSchema>;

export const MessageSchema = Schema.Struct({
  id: Schema.String,
  subject: Schema.NullOr(Schema.String),
  bodyPreview: Schema.String,
  body: BodySchema,
  from: Schema.NullOr(RecipientSchema),
  toRecipients: Schema.Array(RecipientSchema),
  ccRecipients: Schema.Array(RecipientSchema),
  bccRecipients: Schema.optional(Schema.Array(RecipientSchema)),
  receivedDateTime: Schema.DateFromString,
  sentDateTime: Schema.DateFromString,
  isRead: Schema.Boolean,
  isDraft: Schema.Boolean,
  hasAttachments: Schema.Boolean,
  importance: Schema.Literal("low", "normal", "high"),
  conversationId: Schema.NullOr(Schema.String),
  parentFolderId: Schema.String,
  webLink: Schema.optional(Schema.String),
  internetMessageId: Schema.optional(Schema.NullOr(Schema.String)),
  replyTo: Schema.optional(Schema.Array(RecipientSchema)),
  flag: Schema.optional(
    Schema.Struct({
      flagStatus: Schema.Literal("notFlagged", "complete", "flagged"),
    }),
  ),
  categories: Schema.optional(Schema.Array(Schema.String)),
  changeKey: Schema.optional(Schema.String),
  etag: Schema.optional(Schema.String),
});

export type Message = Schema.Schema.Type<typeof MessageSchema>;

export const SendMailPayloadSchema = Schema.Struct({
  message: Schema.Struct({
    subject: Schema.String,
    body: BodySchema,
    toRecipients: Schema.Array(RecipientSchema),
    ccRecipients: Schema.optional(Schema.Array(RecipientSchema)),
    bccRecipients: Schema.optional(Schema.Array(RecipientSchema)),
    replyTo: Schema.optional(Schema.Array(RecipientSchema)),
    importance: Schema.optional(Schema.Literal("low", "normal", "high")),
    attachments: Schema.optional(
      Schema.Array(
        Schema.Struct({
          "@odata.type": Schema.Literal(
            "#microsoft.graph.fileAttachment",
            "#microsoft.graph.itemAttachment",
            "#microsoft.graph.referenceAttachment",
          ),
          name: Schema.String,
          contentType: Schema.optional(Schema.String),
          contentBytes: Schema.optional(Schema.String),
          isInline: Schema.optional(Schema.Boolean),
        }),
      ),
    ),
  }),
  saveToSentItems: Schema.optional(Schema.Boolean),
});

export type SendMailPayload = Schema.Schema.Type<typeof SendMailPayloadSchema>;
