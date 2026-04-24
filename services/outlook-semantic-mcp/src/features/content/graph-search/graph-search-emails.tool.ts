import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { GraphSearchEmailsQuery } from './graph-search-emails.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { META } from '~/features/content/search/search-emails-tool.meta';

const SearchEmailResultSchema = z.object({
  id: z.string(),
  emailId: z.string(),
  folderId: z.string(),
  title: z.string(),
  from: z.string(),
  receivedDateTime: z.string().optional().nullable(),
  text: z.string(),
  outlookWebLink: z.string().optional(),
  url: z.string().optional(),
});

const SearchEmailsOutputSchema = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  results: z.array(SearchEmailResultSchema).optional(),
  status: z.string().optional(),
  searchSummary: z.string().optional(),
});

@Injectable()
export class GraphSearchEmailsTool {
  public constructor(private readonly graphSearchEmailsQuery: GraphSearchEmailsQuery) {}

  @Tool({
    name: 'search_emails',
    title: 'Search Emails',
    description:
      "Search emails with optional structured filters. Returns matched emails with metadata.\n\nTo filter by folder, call `list_folders` first to obtain valid folder IDs. To filter by category, call `list_categories` first to obtain valid category names. To read the full body of a result, call `open_email_by_id` with the result's id.",
    parameters: SearchEmailsInputSchema,
    outputSchema: SearchEmailsOutputSchema,
    annotations: {
      title: 'Search Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async searchEmails(
    input: z.infer<typeof SearchEmailsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchEmailsOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);
    const results = await this.graphSearchEmailsQuery.run(userProfileTypeId.toString(), input);
    return { success: true, results };
  }
}
