import { isNonNull } from 'remeda';
import { GraphMessage } from '../dtos/microsoft-graph.dtos';

export const getMetadataFromMessage = (message: GraphMessage): Record<string, string> => {
  return {
    id: message.id,
    internetMessageId: message.internetMessageId ?? '',
    conversationId: message.conversationId ?? '',
    parentFolderId: message.parentFolderId ?? '',
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
    isRead: `${message.isRead ?? 'false'}`,
    isDraft: `${message.isDraft ?? 'false'}`,
    hasAttachments: `${message.hasAttachments ?? 'false'}`,
    importance: message.importance ?? '',
    inferenceClassification: message.inferenceClassification ?? '',
    'flag.flagStatus': message.flag?.flagStatus ?? '',
  };
};
