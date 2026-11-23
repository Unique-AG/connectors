import { encodeGraphItemIdForUrlPath } from './encode-graph-item-id-for-url-path';

/**
 * The Graph path of a message: in the signed-in user's own mailbox, in a shared mailbox, or in a
 * folder of a shared mailbox, which is the only way in when access is granted per folder.
 */
export function graphMessagePath({
  messageId,
  mailbox,
  folderId,
}: {
  messageId: string;
  mailbox?: string;
  folderId?: string;
}): string {
  const encodedMessageId = encodeGraphItemIdForUrlPath(messageId);
  if (!mailbox) {
    return `/me/messages/${encodedMessageId}`;
  }
  return folderId
    ? `/users/${mailbox}/mailFolders/${encodeGraphItemIdForUrlPath(folderId)}/messages/${encodedMessageId}`
    : `/users/${mailbox}/messages/${encodedMessageId}`;
}
