import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ListCategoriesQuery, ListCategoriesQueryOutputSchema } from './list-categories.query';
import { GetSubscriptionStatusQuery } from '../subscriptions/get-subscription-status.query';

const InputSchema = z.object({});

@Injectable()
export class ListCategoriesTool {
  public constructor(
    private readonly listCategoriesQuery: ListCategoriesQuery,
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
  ) {}

  @Tool({
    name: 'list_categories',
    title: 'List Categories',
    description:
      'List all Outlook mail categories available for the user. Returns the display names of all master categories configured in Outlook.',
    parameters: InputSchema,
    outputSchema: ListCategoriesQueryOutputSchema,
    annotations: {
      title: 'List Categories',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'tag',
      'unique.app/system-prompt':
        'Returns the list of Outlook mail category names configured for the user. Use category names when filtering emails by category. Call this tool when the user wants to know which categories are available or wants to search emails by category.',
    },
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
