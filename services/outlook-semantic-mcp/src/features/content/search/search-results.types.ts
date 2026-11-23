import { Nullish } from '~/utils/nullish';

export enum SearchBackend {
  Unique = 'Unique',
  MsGraph = 'MsGraph',
}

export interface OpenEmailParams {
  id: string;
  mailbox?: string;
  parentFolderId?: string;
  idIsImmutable?: boolean;
  // html for a draft, so the edit reads the live body. Absent means plain text.
  bodyContentType?: 'html';
  // Set when semantic search matched this email. open_email loads these chunks in addition to the Graph body.
  uniqueContentId?: string;
  chunkIds?: string[];
}

export interface ReplyToParams {
  inReplyToMessageId?: string;
  idIsImmutable?: boolean;
  isReplyable: boolean;
}

export interface SearchEmailResult {
  uniqueContentId?: string;
  msGraphMessageId: string;
  folderId: string;
  title: string;
  from: string;
  sourceMailbox: Nullish<string>;
  outlookWebLink: string;
  receivedDateTime: string | null;
  isDraft: boolean;
  text: string;
  uniqueContentUrl: string | undefined;
  backend: SearchBackend;
  openEmailParams: OpenEmailParams;
  replyToParams: ReplyToParams;
}

export enum SearchPageStatus {
  HasMore = 'hasMore',
  // Did not run in this response because the response budget was used up.
  Deferred = 'deferred',
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
