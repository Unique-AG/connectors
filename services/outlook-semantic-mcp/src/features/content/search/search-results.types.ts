import { Nullish } from '~/utils/nullish';

export enum SearchBackend {
  Unique = 'Unique',
  MsGraph = 'MsGraph',
}

export interface OpenEmailParams {
  id: string;
  idType: SearchBackend;
  mailbox?: string;
  parentFolderId?: string;
  idIsImmutable?: boolean;
}

export interface ReplyToParams {
  inReplyToMessageId?: string;
  idIsImmutable?: boolean;
  isReplyable: boolean;
}

export interface SearchEmailResult {
  uniqueContentId?: string;
  msGraphMessageId?: string;
  folderId: string;
  title: string;
  from: string;
  sourceMailbox: Nullish<string>;
  outlookWebLink: string;
  receivedDateTime: string | null;
  text: string;
  uniqueContentUrl: string | undefined;
  backend: SearchBackend;
  openEmailParams: OpenEmailParams;
  replyToParams: ReplyToParams;
}

export enum SearchPageStatus {
  HasMore = 'hasMore',
  Complete = 'complete',
  CeilingReached = 'ceilingReached',
  Throttled = 'throttled',
  Failed = 'failed',
  Expired = 'expired',
  AccessRevoked = 'accessRevoked',
}

// Outcome of one backend request chain (one Graph request or one semantic search) as returned to
// the agent.
export interface SearchPage {
  backend: SearchBackend;
  query: string;
  mailbox?: string;
  folder?: string;
  status: SearchPageStatus;
  cursorId?: string;
  retryAfterSeconds?: number;
}
