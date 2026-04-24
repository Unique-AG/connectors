import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { META } from '~/features/content/open-email-tool.meta';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GraphOpenEmailQuery } from './graph-open-email.query';

const OpenEmailByIdInputSchema = z.object({
  id: z.string().describe('The Graph message ID returned by search_emails.'),
});

const OpenEmailByIdOutputSchema = z.object({
  success: z.boolean(),
  status: z.string().optional(),
  message: z.string().optional(),
  emailData: z
    .object({
      id: z.string(),
      title: z.string().nullable(),
      metadata: z.unknown().nullable(),
      chunks: z
        .array(
          z.object({
            id: z.string(),
            startPage: z.number().nullable(),
            endPage: z.number().nullable(),
            order: z.number(),
            text: z.string(),
          }),
        )
        .optional(),
    })
    .optional(),
});

@Injectable()
export class GraphOpenEmailTool {
  public constructor(private readonly graphOpenEmailQuery: GraphOpenEmailQuery) {}

  @Tool({
    name: 'open_email_by_id',
    title: 'Open Email by ID',
    description: 'Retrieve the full content of an email by its ID returned from search_emails.',
    parameters: OpenEmailByIdInputSchema,
    outputSchema: OpenEmailByIdOutputSchema,
    annotations: {
      title: 'Open Email by ID',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async openEmailById(
    input: z.infer<typeof OpenEmailByIdInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof OpenEmailByIdOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);
    const result = await this.graphOpenEmailQuery.run(userProfileTypeId.toString(), input.id);
    return { success: true, emailData: result };
  }
}
