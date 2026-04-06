import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetSubscriptionStatusQuery } from '../../subscriptions/get-subscription-status.query';
import { LookupContactsQuery, LookupContactsResultSchema } from '../lookup-contacts.query';
import { META } from './lookup-contacts-tool.meta';

const LookupContactsInputSchema = z.object({
  name: z
    .string()
    .min(2)
    .describe('The name (or partial name) to search for among contacts, e.g. "Alice" or "Smith".'),
});

@Injectable()
export class LookupContactsTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly lookupContactsQuery: LookupContactsQuery,
  ) {}

  @Tool({
    name: 'os_mcp_lookup_contacts',
    title: 'Lookup Contacts',
    description:
      'Searches for contacts by name across the Microsoft People API and the connected Outlook inbox. Returns matching contacts with their name, email address, and source.',
    parameters: LookupContactsInputSchema,
    outputSchema: LookupContactsResultSchema,
    annotations: {
      title: 'Lookup Contacts',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async lookupContacts(
    input: z.infer<typeof LookupContactsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeId = extractUserProfileId(request);
    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }
    return await this.lookupContactsQuery.run(userProfileTypeId, input.name);
  }
}
