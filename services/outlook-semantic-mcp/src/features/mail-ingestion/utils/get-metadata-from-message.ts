// import { ContentMetadataValue } from '@unique-ag/unique-api';
import { filter, isNonNullish, map, pipe } from 'remeda';
import { GraphMessage } from '../dtos/microsoft-graph.dtos';

// We should never user `.` in metadata search because Qdrant thinks this is a subobject
export interface MessageMetadata {
  id: string;
  subject: string;
  internetMessageId: string;
  conversationId: string;
  parentFolderId: string;
  sentDateTime: string;
  lastModifiedDateTime: string;
  fromEmailAddress: string;
  fromName: string;
  senderEmailAddress: string;
  senderName: string;
  toRecipientsEmailAddresses: string[];
  toRecipientsNames: string[];
  receivedDateTime: string;
  ccRecipientsEmailAddresses: string[];
  ccRecipientsNames: string[];
  categories: string[];
  isRead: boolean;
  isDraft: boolean;
  hasAttachments: boolean;
  importance: string;
  inferenceClassification: string;
  webLink: string;
  flagStatus: string;
}

const filterOutNilOrEmptyValues = (
  input: (string | null | undefined)[] | null | undefined,
): string[] => {
  if (!input) {
    return [];
  }

  return pipe(
    input,
    filter(isNonNullish),
    map((value) => value.trim()),
    filter((value) => value.length > 0),
  );
};

interface EmailAddress {
  address?: string | undefined | null;
  name?: string | undefined | null;
}

const extractFromEmailArray = (
  input:
    | {
        emailAddress?: EmailAddress | undefined | null;
      }[]
    | undefined
    | null,
  prop: keyof EmailAddress,
): string[] => {
  return filterOutNilOrEmptyValues(input?.map((item) => item.emailAddress?.[prop]));
};

export const getMetadataFromMessage = (message: GraphMessage): MessageMetadata => {
  return {
    id: message.id,
    subject: message.subject ?? '',
    internetMessageId: message.internetMessageId ?? '',
    conversationId: message.conversationId ?? '',
    parentFolderId: message.parentFolderId ?? '',
    sentDateTime: message.sentDateTime ?? '',
    lastModifiedDateTime: message.lastModifiedDateTime ?? '',
    fromEmailAddress: message.from?.emailAddress?.address ?? '',
    fromName: message.from?.emailAddress?.name ?? '',
    senderEmailAddress: message.sender?.emailAddress?.address ?? '',
    senderName: message.sender?.emailAddress?.name ?? '',
    toRecipientsEmailAddresses: extractFromEmailArray(message.toRecipients, 'address'),
    toRecipientsNames: extractFromEmailArray(message.toRecipients, 'name'),
    receivedDateTime: message.receivedDateTime ?? '',
    ccRecipientsEmailAddresses: extractFromEmailArray(message.ccRecipients, 'address'),
    ccRecipientsNames: extractFromEmailArray(message.ccRecipients, 'name'),
    categories: filterOutNilOrEmptyValues(message.categories),
    isRead: message.isRead ?? false,
    isDraft: message.isDraft ?? false,
    webLink: message.webLink ?? '',
    hasAttachments: message.hasAttachments ?? false,
    importance: message.importance ?? '',
    inferenceClassification: message.inferenceClassification ?? '',
    flagStatus: message.flag?.flagStatus ?? '',
  };
};
