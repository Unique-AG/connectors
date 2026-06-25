import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import {
  SearchEmailsMsGraphInputSchema,
  SearchEmailsUnifiedInputSchema,
} from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { GetFullSyncStatsQuery } from '~/features/sync/full-sync/get-full-sync-stats.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { META_MS_GRAPH, META_UNIQUE_AND_MS_GRAPH } from './search-emails-tool.meta';
import { SearchBackend } from './semantic-search-emails.query';

const SearchEmailsToolInputSchema = isMicrosoftGraphBackend()
  ? SearchEmailsMsGraphInputSchema
  : SearchEmailsUnifiedInputSchema;

const SearchEmailsToolDescription = isMicrosoftGraphBackend()
  ? 'Search emails using Microsoft Graph KQL queries across your own and delegated mailboxes. Returns matched emails — the `text` field contains the full email body, so you can answer questions about email content directly without calling `open_email`. Only call `open_email` if the user explicitly asks to open or view an email.\n\nIf the response includes `searchNotes`, display them to the user after results.'
  : 'Search emails semantically with optional structured filters. Returns matched email passages with an id per result.\n\nTo filter by a well-known folder (Inbox, Sent Items, Drafts, etc.) pass the name directly in `directories` — no need to call `list_mailboxes_and_directories`. For custom folders, call `list_mailboxes_and_directories` first to get the folder id. To filter by category, call `list_categories` first to obtain valid category names. To read the full body of a result, call `open_email` passing the `openEmailParams` object from the result directly as the tool input. If the response includes a `syncWarning`, call `sync_progress` to check ingestion status — results may be incomplete. If the response includes `searchNotes`, display them to the user after results.';

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
      'Microsoft Graph message ID. Pass as `id` with `idType: "MsGraph"` to `open_email`. Present for Graph-backend results; also present for semantic results when both backends matched the same email.',
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
      'Email content, structured with markdown section headers depending on which backends matched:\n' +
        '- `## Semantically Matched Content` — relevant excerpts or passages that matched the semantic query. May be incomplete; call `open_email` if the full body is needed.\n' +
        '- `## Full Email Content Without Attachments` — complete email body text (no attachments). Use this to answer questions about email content directly without calling `open_email`.\n' +
        'When both sections are present, prefer `## Full Email Content Without Attachments` for answering content questions — it is the complete body. `## Semantically Matched Content` highlights the most relevant passages.\n' +
        'When only `## Semantically Matched Content` is present, use it to answer but note the content may be a partial excerpt.',
    ),
  outlookWebLink: z
    .string()
    .describe(
      'Direct URL to open this email in Outlook on the web. When non-empty, use it as the link target. When empty (delegated mailbox results), do NOT construct a URL — show the subject as plain text instead.',
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
      'Pre-constructed input for `open_email`. Pass this object directly as the tool input without modification.',
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

const SearchEmailsOutputSchema = z.object({
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
    .describe('Matched emails. Present when `success` is `true`.'),
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
      'Informational notes about the search run, e.g. unrecognized folders that were excluded or mailboxes that were partially unavailable. Display to the user after results when present.',
    ),
});

@Injectable()
export class SearchEmailsTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly searchEmailsQuery: SearchEmailsQuery,
    private readonly getFullSyncStatsQuery: GetFullSyncStatsQuery,
  ) {}

  @Tool({
    name: 'search_emails',
    title: 'Search Emails',
    description: SearchEmailsToolDescription,
    parameters: SearchEmailsToolInputSchema,
    outputSchema: SearchEmailsOutputSchema,
    annotations: {
      title: 'Search Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: isMicrosoftGraphBackend() ? META_MS_GRAPH : META_UNIQUE_AND_MS_GRAPH,
  })
  @Span()
  public async searchEmails(
    input: z.infer<typeof SearchEmailsToolInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchEmailsOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);

    if (!isMicrosoftGraphBackend()) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const { results, searchSummary } = await this.searchEmailsQuery.run(userProfileTypeId, input);

    if (!isMicrosoftGraphBackend()) {
      const stats = await this.getFullSyncStatsQuery.run(userProfileTypeId);

      let syncWarning: string | undefined;
      if (stats.state === 'error' || stats.state === 'running') {
        syncWarning = `Your mailbox is still being indexed — searching through your emails will improve over time.`;
      }
      return {
        success: true,
        syncWarning,
        searchNotes: searchSummary,
        results,
      };
    }

    return { success: true, results, searchNotes: searchSummary };
  }
}
