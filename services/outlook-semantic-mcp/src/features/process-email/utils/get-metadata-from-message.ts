import { asAllOptions } from '@unique-ag/utils';
import { filter, isNonNullish, map, pick, pipe } from 'remeda';
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
  isRead: 'true' | 'false';
  isDraft: 'true' | 'false';
  hasAttachments: 'true' | 'false';
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

const booleanToString = (value: boolean | null | undefined) => (value ? 'true' : 'false');

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
    isRead: booleanToString(message.isRead),
    isDraft: booleanToString(message.isDraft),
    hasAttachments: booleanToString(message.hasAttachments),
    webLink: message.webLink ?? '',
    importance: message.importance ?? '',
    inferenceClassification: message.inferenceClassification ?? '',
    flagStatus: message.flag?.flagStatus ?? '',
  };
};

export const extractMetadataKeys = (data: Record<string, unknown>) =>
  pick(
    data,
    asAllOptions<keyof MessageMetadata>()([
      `id`,
      `subject`,
      `internetMessageId`,
      `conversationId`,
      `parentFolderId`,
      `sentDateTime`,
      `lastModifiedDateTime`,
      `fromEmailAddress`,
      `fromName`,
      `senderEmailAddress`,
      `senderName`,
      `toRecipientsEmailAddresses`,
      `toRecipientsNames`,
      `receivedDateTime`,
      `ccRecipientsEmailAddresses`,
      `ccRecipientsNames`,
      `categories`,
      `isRead`,
      `isDraft`,
      `webLink`,
      `hasAttachments`,
      `importance`,
      `inferenceClassification`,
      `flagStatus`,
    ]),
  );
