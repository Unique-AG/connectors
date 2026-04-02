import { createHash } from 'node:crypto';
import { GraphMessage } from '../dtos/microsoft-graph.dtos';
import assert from 'node:assert';

export const getUniqueKeyForMessage = (
  userEmail: string,
  message: Pick<GraphMessage, 'id'>,
): string => {
  // We hash the email to obfuscate it in the UI and in any other logs.
  const emailInSha256 = createHash('sha256').update(userEmail.trim()).digest('hex');
  assert.ok(message.id, `Cannot create uniquer file key message.id is required`);
  // We use message.id (the Graph API immutable ID) rather than internetMessageId because
  // internetMessageId is an SMTP header shared across all copies of a message — if a user
  // sends an email to themselves, both the sent copy and the received copy have the same
  // internetMessageId, making it unsuitable as a unique key. message.id is stable across
  // folder moves within the primary mailbox (e.g. Inbox → Archive folder), but note that
  // the archive mailbox is a separate mailbox in Exchange Online and messages there have
  // different IDs.
  return `MessageId:${message.id}|User:${emailInSha256}`;
};
