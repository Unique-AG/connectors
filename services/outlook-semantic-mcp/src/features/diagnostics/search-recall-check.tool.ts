import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { RunSearchRecallCheckQuery } from './run-search-recall-check.query';

const META = createMeta({
  icon: 'search',
  systemPrompt:
    'Runs search queries against the Unique index and checks whether expected emails appear in results. Use when investigating whether missing emails are a retrieval problem versus an ingestion problem.',
});

const InputSchema = z.object({
  cases: z
    .array(
      z.object({
        id: z.string(),
        expectedMessageIds: z.array(z.string()).min(1),
        search: SearchEmailsInputSchema,
      }),
    )
    .min(1)
    .max(20),
});

const OutputSchema = z.object({
  results: z.array(
    z.object({
      id: z.string(),
      checkStatus: z.enum(['success', 'failure']),
      missedMessages: z.array(
        z.object({
          messageId: z.string(),
          fileKey: z.string(),
        }),
      ),
    }),
  ),
});

@Injectable()
export class SearchRecallCheckTool {
  public constructor(private readonly runSearchRecallCheckQuery: RunSearchRecallCheckQuery) {}

  @Tool({
    name: 'search_recall_check',
    title: 'Search Recall Check',
    description:
      'Checks whether known emails are returned for a set of search queries. For each test case, runs the query through the same search path the agent uses and reports which expected emails were missed.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Search Recall Check',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async searchRecallCheck(
    input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof OutputSchema>> {
    const userProfileId = extractUserProfileId(request).toString();
    return await this.runSearchRecallCheckQuery.run(userProfileId, input.cases);
  }
}
