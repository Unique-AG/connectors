import * as z from 'zod';
import { SEARCH_CONFIG } from './search.config';
import { SearchBackend, SearchPageStatus } from './search-results.types';

const SearchEmailResultSchema = z.object({
  uniqueContentId: z
    .string()
    .optional()
    .describe(
      'Semantic-backend content ID. Pass as `id` with `idType: "Unique"` to `open_email`. Present only for semantic-backend results.',
    ),
  msGraphMessageId: z
    .string()
    .optional()
    .describe(
      'Microsoft Graph message ID. Pass as `id` with `idType: "MsGraph"` to `open_email`. Present for Graph-backend results; also present for semantic results when both backends matched the same email. Use it to recognise the same email returned on different pages.',
    ),
  folderId: z
    .string()
    .describe(
      'ID of the folder containing this email. Internal identifier — do not display to the user.',
    ),
  title: z.string().describe('Subject line of the email.'),
  from: z.string().describe('Sender email address.'),
  receivedDateTime: z
    .string()
    .optional()
    .nullable()
    .describe('Date and time the email was received, in ISO 8601 format.'),
  text: z
    .string()
    .describe(
      'Partial email content — never the full body. Structured with markdown section headers depending on which backends matched:\n' +
        '- `## Semantically Matched Content` — passages of the email or its attachments that matched the semantic query.\n' +
        '- `## Preview` — the first ~255 characters of the email body.\n' +
        'Answer from `text` only when it clearly contains the answer. Otherwise call `open_email` with `openEmailParams` to read the full body.',
    ),
  outlookWebLink: z
    .string()
    .describe(
      'Direct URL to open this email in Outlook on the web. When non-empty, use it as the link target. When empty, show the subject as plain text.',
    ),
  sourceMailbox: z
    .string()
    .nullish()
    .describe(
      'Mailbox this email belongs to (own or delegated). Useful when results span multiple mailboxes.',
    ),
  uniqueContentUrl: z
    .string()
    .optional()
    .describe(
      'Internal URL for the semantic-backend content. For user-facing links, prefer `outlookWebLink`.',
    ),
  backend: z
    .nativeEnum(SearchBackend)
    .describe(
      'Search backend that returned this result: "Unique" (semantic) or "MsGraph" (keyword). Determines which `idType` to use when calling `open_email`.',
    ),
  openEmailParams: z
    .object({
      id: z.string(),
      idType: z.nativeEnum(SearchBackend),
      mailbox: z.string().optional(),
      parentFolderId: z.string().optional(),
      idIsImmutable: z.boolean().optional(),
    })
    .describe(
      'Pre-constructed input for `open_email`. Pass this object directly as the tool input without modification to read the full email.',
    ),
  replyToParams: z
    .object({
      inReplyToMessageId: z
        .string()
        .optional()
        .describe(
          'Microsoft Graph message ID for the reply target. Copy into `recipientsData.inReplyToMessageId` when calling `draft_email` with `type: "reply"`. Absent when no Graph message ID is available.',
        ),
      idIsImmutable: z
        .boolean()
        .optional()
        .describe(
          'Whether `inReplyToMessageId` is an immutable ID. Copy into `recipientsData.idIsImmutable` when calling `draft_email` with `type: "reply"`.',
        ),
      isReplyable: z
        .boolean()
        .describe(
          'Whether this message can be used as a reply target. Do not call `draft_email` with `type: "reply"` when false — pick a different email or explain that a reply is not possible.',
        ),
    })
    .describe(
      'Reply metadata from search. Copy `inReplyToMessageId` and `idIsImmutable` into matching `recipientsData` fields when `isReplyable` is true. Use top-level `mailbox` on `draft_email` (from `sourceMailbox`) for shared or delegated mailboxes.',
    ),
});

export const SEARCH_PAGE_STATUS_DESCRIPTION = [
  'What to do next with this request:',
  '- `hasMore`: more results exist. Call `fetch_next_search_pages` with `cursorId`.',
  '- `complete`: this request returned everything it matched.',
  `- \`ceilingReached\`: results stopped at the ${SEARCH_CONFIG.maxResultsPerChain}-result limit, more emails match. Tell the user the results are capped and narrow the search (e.g. split the date range into smaller windows).`,
  '- `throttled`: Microsoft rate-limited this request (HTTP 429). Wait `retryAfterSeconds`, then retry ONCE with the same `cursorId` via `fetch_next_search_pages`. If it is still throttled, stop retrying and tell the user the results are incomplete.',
  '- `failed`: a temporary error. Retry ONCE with the same `cursorId`; if it fails again, stop retrying. Without a `cursorId` it cannot be retried — check the query syntax. Either way, tell the user the results may be incomplete.',
  '- `expired`: this position can no longer be continued. Run the search again.',
  '- `accessRevoked`: access to this mailbox was lost. Do not retry.',
  'The results are complete only when every entry in `pages` is `complete`. Any other status means some results are missing — tell the user.',
].join('\n');

const SearchPageSchema = z.object({
  backend: z
    .nativeEnum(SearchBackend)
    .describe('"Unique" for a semantic search, "MsGraph" for a KQL query.'),
  query: z.string().describe('The KQL query or semantic search text this request belongs to.'),
  mailbox: z.string().optional().describe('Mailbox searched by this request.'),
  folder: z
    .string()
    .optional()
    .describe('Folder searched by this request, when the query was restricted to folders.'),
  status: z.nativeEnum(SearchPageStatus).describe(SEARCH_PAGE_STATUS_DESCRIPTION),
  cursorId: z
    .string()
    .optional()
    .describe(
      'Pass to `fetch_next_search_pages` exactly as given: for `hasMore` it fetches the next page, for `throttled` or `failed` it retries this page. Internal identifier — do not display to the user.',
    ),
  retryAfterSeconds: z
    .number()
    .optional()
    .describe('For `throttled`: wait at least this many seconds before retrying with `cursorId`.'),
});

export const SearchEmailsOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      '`true` if the search completed; `false` if it was blocked (e.g. subscription not active).',
    ),
  message: z
    .string()
    .optional()
    .describe('Human-readable error description when `success` is `false`.'),
  results: z
    .array(SearchEmailResultSchema)
    .optional()
    .describe('Matched emails on this page. Present when `success` is `true`.'),
  hasMore: z
    .boolean()
    .optional()
    .describe(
      '`true` when at least one entry in `pages` has status `hasMore`. Throttled and failed pages are not counted. `false` does not mean the results are complete: they are complete only when every entry in `pages` is `complete`.',
    ),
  pages: z
    .array(SearchPageSchema)
    .optional()
    .describe(
      'One entry per backend request: per semantic search, and per KQL query × mailbox (× folder). Tells you whether each request is complete and how to continue it. Use `mailbox` and `folder` to decide which cursors to follow; a short first page does not mean the request is exhausted, only its `status` tells.',
    ),
  status: z
    .string()
    .optional()
    .describe('Additional subscription or backend status detail. Informational only.'),
  syncWarning: z
    .string()
    .optional()
    .describe(
      'Present when email ingestion is still in progress or in an error state. Always display this to the user before showing results.',
    ),
  searchNotes: z
    .string()
    .optional()
    .describe(
      'Informational notes about the search run, e.g. unrecognized folders that were excluded, throttled or partially unavailable mailboxes, or unknown cursors. Display to the user after results when present.',
    ),
});

export type SearchEmailsToolOutput = z.infer<typeof SearchEmailsOutputSchema>;
