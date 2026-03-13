export { FileAttachment } from './file-attachment.schema';
export { MailFolder } from './mail-folders.schema';
export { FollowupFlag, Message } from './messages.schema';
export type {
  CreateMessageRequest,
  GetMailFolderRequest,
  GetMailFoldersDeltaRequest,
  GetMessageRequest,
  GetSystemFolderRequest,
  ListMailFoldersRequest,
  ListMessagesRequest,
} from './outlook.requests';
export { OutlookCategory } from './outlook-category.schema';
export { OutlookClient } from './outlook-client';
