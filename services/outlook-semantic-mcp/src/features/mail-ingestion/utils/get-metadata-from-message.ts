import { ContentMetadataValue } from '@unique-ag/unique-api';
import { filter, isNonNullish, map, pipe } from 'remeda';
import { GraphMessage } from '../dtos/microsoft-graph.dtos';

export interface MessageMetadata extends Record<string, ContentMetadataValue> {
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
  'toRecipients.emailAddresses': string[];
  'toRecipients.names': string[];
  receivedDateTime: string;
  'ccRecipients.emailAddresses': string[];
  'ccRecipients.names': string[];
  categories: string[];
  isRead: boolean;
  isDraft: boolean;
  hasAttachments: boolean;
  importance: string;
  inferenceClassification: string;
  'flag.flagStatus': string;
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
  address?: string | undefined;
  name?: string | undefined;
}

const extractFromEmailArray = (
  input:
    | {
        emailAddress?: EmailAddress | undefined;
      }[]
    | undefined,
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
    'from.emailAddress': message.from?.emailAddress?.address ?? '',
    'from.name': message.from?.emailAddress?.name ?? '',
    'sender.emailAddress': message.sender?.emailAddress?.address ?? '',
    'sender.name': message.sender?.emailAddress?.name ?? '',
    'toRecipients.emailAddresses': extractFromEmailArray(message.toRecipients, 'address'),
    'toRecipients.names': extractFromEmailArray(message.toRecipients, 'name'),
    receivedDateTime: message.receivedDateTime ?? '',
    'ccRecipients.emailAddresses': extractFromEmailArray(message.ccRecipients, 'address'),
    'ccRecipients.names': extractFromEmailArray(message.ccRecipients, 'name'),
    categories: filterOutNilOrEmptyValues(message.categories),
    isRead: message.isRead ?? false,
    isDraft: message.isDraft ?? false,
    hasAttachments: message.hasAttachments ?? false,
    importance: message.importance ?? '',
    inferenceClassification: message.inferenceClassification ?? '',
    'flag.flagStatus': message.flag?.flagStatus ?? '',
  };
};
