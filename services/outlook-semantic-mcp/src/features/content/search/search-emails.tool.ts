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

const IS_MICROSOFT_GRAPH_BACKEND = isMicrosoftGraphBackend();

const SearchEmailsToolInputSchema = IS_MICROSOFT_GRAPH_BACKEND
  ? SearchEmailsMsGraphInputSchema
  : SearchEmailsUnifiedInputSchema;

const SearchEmailsToolDescription = IS_MICROSOFT_GRAPH_BACKEND
  ? "Search emails using Microsoft Graph KQL queries. Returns matched emails with an id per result.\n\nIMPORTANT: KQL search only filters the current user's own inbox — delegated-access mailboxes are NOT supported.\n\nTo read the full body of a result, call `open_email_by_id` passing `msGraphMessageId` as `id` and `MsGraph` as `idType`."
  : 'Search emails semantically with optional structured filters. Returns matched email passages with an id per result.\n\nTo filter by a well-known folder (Inbox, Sent Items, Drafts, etc.) pass the name directly in `directories` — no need to call `list_folders`. For custom folders, call `list_folders` first to get the folder id. To filter by category, call `list_categories` first to obtain valid category names. To read the full body of a result, call `open_email_by_id` passing `uniqueContentId` (or `msGraphMessageId` if unavailable) as `id`, and `Unique` (or `MsGraph`) as `idType`. If the response includes a `syncWarning`, call `sync_progress` to check ingestion status — results may be incomplete.';

const SearchEmailResultSchema = z.object({
  uniqueContentId: z
    .string()
    .optional()
    .describe(
      'Semantic-backend content ID. Pass as `id` with `idType: "Unique"` to `open_email_by_id`. Present only for semantic-backend results.',
    ),
  msGraphMessageId: z
    .string()
    .optional()
    .describe(
      'Microsoft Graph message ID. Pass as `id` with `idType: "MsGraph"` to `open_email_by_id`. Present for Graph-backend results; also present for semantic results when both backends matched the same email.',
    ),
  folderId: z
    .string()
    .describe(
      'ID of the folder containing this email. Internal identifier — do not display to the user.',
    ),
  title: z.string().describe('Subject line of the email.'),
  from: z.string().describe('Sender of the email, in "Name <email>" or plain "email" format.'),
  receivedDateTime: z
    .string()
    .optional()
    .nullable()
    .describe('Date and time the email was received, in ISO 8601 format.'),
  text: z
    .string()
    .describe(
      'Matched passage or excerpt from the email body — not the full body. Call `open_email_by_id` to retrieve complete content.',
    ),
  outlookWebLink: z
    .string()
    .describe(
      'Direct URL to open this email in Outlook on the web. Use as the primary link when non-empty; otherwise construct from `msGraphMessageId`.',
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
      'Search backend that returned this result: "Unique" (semantic) or "MsGraph" (keyword). Determines which `idType` to use when calling `open_email_by_id`.',
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
      openWorldHint: false,
    },
    _meta: IS_MICROSOFT_GRAPH_BACKEND ? META_MS_GRAPH : META_UNIQUE_AND_MS_GRAPH,
  })
  @Span()
  public async searchEmails(
    input: z.infer<typeof SearchEmailsToolInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchEmailsOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);

    if (!IS_MICROSOFT_GRAPH_BACKEND) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const { results, searchSummary } = await this.searchEmailsQuery.run(userProfileTypeId, input);

    if (!IS_MICROSOFT_GRAPH_BACKEND) {
      const stats = await this.getFullSyncStatsQuery.run(userProfileTypeId);

      if (stats.state === 'error') {
        return {
          success: true,
          syncWarning:
            'Search results may be inaccurate. Ingestion Statistics could not be fetched. Your inbox is in an unknown state try to use the tools `delete_inbox_data` and `reconnect_inbox` to get it into a proper state',
          results,
        };
      }
      if (stats.state === 'running') {
        return {
          success: true,
          syncWarning:
            'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox. The sync process synchronizes newest emails first.',
          results,
        };
      }
    }

    return { success: true, results, syncWarning: searchSummary };
  }
}
