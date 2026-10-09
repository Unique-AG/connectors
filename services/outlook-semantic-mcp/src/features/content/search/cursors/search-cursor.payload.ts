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
});

export type MsGraphSearchCursorPayload = z.infer<typeof MsGraphSearchCursorPayloadSchema>;

export const UniqueSearchCursorPayloadSchema = z.object({
  backend: z.literal(SearchBackend.Unique),
  input: SearchEmailsInputSchema,
  page: z.number().int().nonnegative(),
  // Emails already returned on this chain. Later pages carry further chunks of the same emails,
  // which are dropped.
  seenContentIds: z.array(z.string()),
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
}

// A page outcome produced by a backend, before its continuation is stored as a cursor.
export interface BackendPage extends Omit<SearchPage, 'cursorId'> {
  // Position to continue or retry from. Absent when the chain cannot be continued.
  continuation?: SearchCursorPayload;
  // Cursor the page was fetched from, returned unchanged when the same position must be retried.
  retryCursorId?: string;
}
