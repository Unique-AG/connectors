import { Message } from '@microsoft/microsoft-graph-types';
import { snakeCase } from 'lodash';
import { EmailInput } from '../../../drizzle';

export const mapOutlookMessageToEmailInput = ({
  message,
  userProfileId,
  folderId,
  foldersMap,
}: {
  message: Message;
  userProfileId: string;
  folderId: string;
  foldersMap: Map<string, string>;
}): EmailInput => {
  const tags: string[] = [];

  if (message.importance) tags.push(`importance:${snakeCase(message.importance)}`);

  if (message.parentFolderId && foldersMap?.get(message.parentFolderId))
    tags.push(`folder:${snakeCase(foldersMap.get(message.parentFolderId))}`);

  return {
    // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
    messageId: message.id!,
    conversationId: message.conversationId,
    internetMessageId: message.internetMessageId,
    webLink: message.webLink,
    version: message.changeKey,

    from: message.from
      ? {
          name: message.from.emailAddress?.name || null,
          address: message.from.emailAddress?.address || '',
        }
      : null,
    sender: message.sender
      ? {
          name: message.sender.emailAddress?.name || null,
          address: message.sender.emailAddress?.address || '',
        }
      : null,
    replyTo: message.replyTo?.map((r) => ({
      name: r.emailAddress?.name || null,
      address: r.emailAddress?.address || '',
    })),
    to:
      message.toRecipients?.map((r) => ({
        name: r.emailAddress?.name || null,
        address: r.emailAddress?.address || '',
      })) || [],
    cc:
      message.ccRecipients?.map((r) => ({
        name: r.emailAddress?.name || null,
        address: r.emailAddress?.address || '',
      })) || [],
    bcc:
      message.bccRecipients?.map((r) => ({
        name: r.emailAddress?.name || null,
        address: r.emailAddress?.address || '',
      })) || [],

    sentAt: message.sentDateTime,
    receivedAt: message.receivedDateTime,

    subject: message.subject,
    preview: message.bodyPreview,
    bodyText: message.body?.contentType === 'text' ? message.body?.content : null,
    bodyHtml: message.body?.contentType === 'html' ? message.body?.content : null,

    uniqueBodyText: message.uniqueBody?.contentType === 'text' ? message.uniqueBody?.content : null,
    uniqueBodyHtml: message.uniqueBody?.contentType === 'html' ? message.uniqueBody?.content : null,

    isRead: message.isRead || false,
    isDraft: message.isDraft || false,

    tags,

    hasAttachments: message.hasAttachments || false,
    attachments: message.attachments?.map((attachment) => ({
      id: attachment.id,
      filename: attachment.name,
      mimeType: attachment.contentType,
      sizeBytes: attachment.size,
      isInline: attachment.isInline,
    })),
    attachmentCount: message.attachments?.length || 0,

    headers: message.internetMessageHeaders?.map((header) => ({
      // biome-ignore lint/style/noNonNullAssertion: MS Graph does not send headers without a name.
      name: header.name!,
      value: header.value,
    })),

    userProfileId,
    folderId,
  };
};
