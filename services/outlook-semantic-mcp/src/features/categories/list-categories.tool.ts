import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetSubscriptionStatusQuery } from '../subscriptions/get-subscription-status.query';
import { ListCategoriesQuery, ListCategoriesQueryOutputSchema } from './list-categories.query';
import { META } from './list-categories-tool.meta';

const InputSchema = z.object({});

@Injectable()
export class ListCategoriesTool {
  public constructor(
    private readonly listCategoriesQuery: ListCategoriesQuery,
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
  ) {}

  @Tool({
    name: 'os_mcp_list_categories',
    title: 'List Categories',
    description:
      'List all Outlook mail categories available for the user. Returns display names of all master categories configured in Outlook. Category names can be passed to the `categories` filter in `os_mcp_search_emails` to narrow results.',
    parameters: InputSchema,
    outputSchema: ListCategoriesQueryOutputSchema,
    annotations: {
      title: 'List Categories',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async listCategories(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof ListCategoriesQueryOutputSchema>> {
    const userProfileId = extractUserProfileId(request);
    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileId);

    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }
    return this.listCategoriesQuery.run(userProfileId);
  }
}
