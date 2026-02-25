import { isNonNull } from 'remeda';
import { GraphMessage } from '../dtos/microsoft-graph.dtos';

export interface MessageMetadata extends Record<string, string> {
  id: string;
  subject: string;
  internetMessageId: string;
  conversationId: string;
  parentFolderId: string;
  sentDateTime: string;
  lastModifiedDateTime: string;
  'from.emailAddress': string;
  'from.name': string;
  'sender.emailAddress': string;
  'sender.name': string;
  'toRecipients.emailAddresses': string;
  'toRecipients.names': string;
  receivedDateTime: string;
  'ccRecipients.emailAddresses': string;
  'ccRecipients.names': string;
  categories: string;
  isRead: string;
  isDraft: string;
  hasAttachments: string;
  importance: string;
  inferenceClassification: string;
  'flag.flagStatus': string;
}

export const getMetadataFromMessage = (message: GraphMessage): MessageMetadata => {
  return {
    id: message.id,
    subject: message.subject ?? '',
    internetMessageId: message.internetMessageId ?? '',
    conversationId: message.conversationId ?? '',
    parentFolderId: message.parentFolderId ?? '',
    sentDateTime: message.sentDateTime ?? '',
    lastModifiedDateTime: message.lastModifiedDateTime ?? '',
    'from.emailAddress': message.from?.emailAddress?.address ?? '',
    'from.name': message.from?.emailAddress?.name ?? '',
    'sender.emailAddress': message.sender?.emailAddress?.address ?? '',
    'sender.name': message.sender?.emailAddress?.name ?? '',
    'toRecipients.emailAddresses':
      message.toRecipients
        ?.map((item) => item.emailAddress?.address)
        .filter(isNonNull)
        .join(',') ?? '',
    'toRecipients.names':
      message.toRecipients
        ?.map((item) => item.emailAddress?.name)
        .filter(isNonNull)
        .join(',') ?? '',
    receivedDateTime: message.receivedDateTime ?? '',
    'ccRecipients.emailAddresses':
      message.ccRecipients
        ?.map((item) => item.emailAddress?.address)
        .filter(isNonNull)
        .join(',') ?? '',
    'ccRecipients.names':
      message.ccRecipients
        ?.map((item) => item.emailAddress?.name)
        .filter(isNonNull)
        .join(',') ?? '',
    categories: message.categories?.join(',') ?? '',
    isRead: `${message.isRead ?? 'false'}`,
    isDraft: `${message.isDraft ?? 'false'}`,
    hasAttachments: `${message.hasAttachments ?? 'false'}`,
    importance: message.importance ?? '',
    inferenceClassification: message.inferenceClassification ?? '',
    'flag.flagStatus': message.flag?.flagStatus ?? '',
  };
};
