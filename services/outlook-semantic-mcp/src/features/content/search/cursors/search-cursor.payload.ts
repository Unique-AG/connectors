import * as z from 'zod';
import { SearchEmailsInputSchema } from '../search-conditions.dto';
import { SearchBackend, SearchPage } from '../search-results.types';

export const MsGraphSearchCursorPayloadSchema = z.object({
  backend: z.literal(SearchBackend.MsGraph),
  kqlQuery: z.string(),
  mailbox: z.string(),
  isDelegated: z.boolean(),
  folderId: z.string().optional(),
  folderName: z.string().optional(),
  // Graph URL relative to the API version root: an @odata.nextLink, or the first-page URL when
  // that page could not be fetched.
  url: z.string(),
  // Results already returned on this chain, used to detect the 1,000-result $search ceiling.
  delivered: z.number().int().nonnegative(),
  // Newest result of the chain's first page. Graph answers a nextLink it can no longer use with
  // the first page again instead of an error, so a later page holding this or a newer email means
  // the chain restarted. Absent until the first page has been delivered.
  chainHead: z.object({ id: z.string(), sentDateTime: z.string() }).optional(),
});

export type MsGraphSearchCursorPayload = z.infer<typeof MsGraphSearchCursorPayloadSchema>;

export const UniqueSearchCursorPayloadSchema = z.object({
  backend: z.literal(SearchBackend.Unique),
  input: SearchEmailsInputSchema,
  // Unique search pages start at 1.
  page: z.number().int().positive(),
  // Chunks already returned on this chain. Unique pages its vector and full-text searches
  // separately, so a chunk can come back on a later page; it is dropped there.
  seenChunkIds: z.array(z.string()),
});

export type UniqueSearchCursorPayload = z.infer<typeof UniqueSearchCursorPayloadSchema>;

export const SearchCursorPayloadSchema = z.discriminatedUnion('backend', [
  MsGraphSearchCursorPayloadSchema,
  UniqueSearchCursorPayloadSchema,
]);

export type SearchCursorPayload = z.infer<typeof SearchCursorPayloadSchema>;

export interface StoredSearchCursor<T extends SearchCursorPayload = SearchCursorPayload> {
  id: string;
  payload: T;
  createdAt: Date;
}

// A page outcome produced by a backend, before its continuation is stored as a cursor.
export interface BackendPage extends Omit<SearchPage, 'cursorId'> {
  // Position to continue or retry from. Absent when the chain cannot be continued.
  continuation?: SearchCursorPayload;
  // Cursor the page was fetched from, returned unchanged when the same position must be retried.
  retryCursorId?: string;
}
