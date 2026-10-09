import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { META } from './fetch-next-search-pages-tool.meta';
import { SEARCH_CONFIG } from './search.config';
import { SearchEmailsQuery } from './search-emails.query';
import { SearchEmailsOutputSchema, SearchEmailsToolOutput } from './search-emails-output.schema';

const FetchNextSearchPagesInputSchema = z.object({
  cursorIds: z
    .array(z.string().nonempty())
    .min(1)
    .max(SEARCH_CONFIG.maxCursorsPerFetch)
    .describe(
      `Cursor ids copied exactly from \`pages[].cursorId\` of a \`search_emails\` or \`fetch_next_search_pages\` response. At most ${SEARCH_CONFIG.maxCursorsPerFetch} per call — when there are more, call this tool again with the rest.`,
    ),
});

@Injectable()
export class FetchNextSearchPagesTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly searchEmailsQuery: SearchEmailsQuery,
  ) {}

  @Tool({
    name: 'fetch_next_search_pages',
    title: 'Fetch Next Search Pages',
    description:
      'Fetch the next page of results, or retry a throttled or failed page, for searches started with `search_emails`. ' +
      'Pass the `cursorId`s from `pages`. Returns the same shape as `search_emails`: the new `results`, and a `pages` list with fresh `cursorId`s for whatever can still be continued. ' +
      'Following the same `cursorId` again returns the same page, so a retry never skips results. ' +
      'Results carry only partial content in `text` — call `open_email` with `openEmailParams` to read an email in full.',
    parameters: FetchNextSearchPagesInputSchema,
    outputSchema: SearchEmailsOutputSchema,
    annotations: {
      title: 'Fetch Next Search Pages',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async fetchNextSearchPages(
    input: z.infer<typeof FetchNextSearchPagesInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<SearchEmailsToolOutput> {
    const userProfileTypeId = extractUserProfileId(request);

    if (!isMicrosoftGraphBackend()) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const { results, pages, hasMore, searchSummary } = await this.searchEmailsQuery.fetchNextPages(
      userProfileTypeId,
      input.cursorIds,
    );
    return { success: true, results, hasMore, pages, searchNotes: searchSummary };
  }
}
