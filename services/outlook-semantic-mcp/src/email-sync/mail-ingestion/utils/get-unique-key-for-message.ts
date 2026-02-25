import { createHash } from 'node:crypto';
import { isNonNullish } from 'remeda';
import { GraphMessage } from '../dtos/microsoft-graph.dtos';

export const getUniqueKeyForMessage = (
  userEmail: string,
  message: Pick<
    GraphMessage,
    'internetMessageId' | 'id' | 'uniqueBody' | 'toRecipients' | 'from' | 'subject'
  >,
): string => {
  // The following things were considered.
  // 1. We do not use id of the message because it changes when you archive.
  // 2. For draft emails the Fingerprint is not useful cause it changes but I tested it and draft emails have the internetMessageId attached as soon as they are created.
  if (message.internetMessageId) {
    return `Email:${userEmail}|InternetMessageId:${message.internetMessageId}`;
  }

  const toRecipients =
    message.toRecipients?.map((item) => item.emailAddress?.address).filter(isNonNullish) ?? [];

  const fingerprint = [
    ['from', message.from?.emailAddress],
    ['to', toRecipients.sort().join(',')],
    ['subject', message.subject?.trim() ?? ''],
    ['uniqueBody', message.uniqueBody?.content?.toString() ?? ''],
  ]
    .map((item) => item.join(':'))
    .join(`|`);

  return `Email:${userEmail}|Fingerprint:${createHash('sha256').update(fingerprint).digest('hex')}`;
};
