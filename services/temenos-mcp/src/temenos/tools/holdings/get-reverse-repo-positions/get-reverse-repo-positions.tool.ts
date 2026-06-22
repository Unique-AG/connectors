import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetReverseRepoPositionsInputSchema,
  GetReverseRepoPositionsOutputSchema,
  GetReverseRepoPositionsQuery,
  type GetReverseRepoPositionsResult,
} from './get-reverse-repo-positions.query';
import { META } from './get-reverse-repo-positions-tool.meta';

@Injectable()
export class GetReverseRepoPositionsTool {
  public constructor(private readonly query: GetReverseRepoPositionsQuery) {}

  @Tool({
    name: 'get_reverse_repo_positions',
    title: 'Get Reverse Repo Positions',
    description: 'Retrieve reverse repurchase agreement current positions from Temenos.',
    parameters: GetReverseRepoPositionsInputSchema,
    outputSchema: GetReverseRepoPositionsOutputSchema,
    annotations: {
      title: 'Get Reverse Repo Positions',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getReverseRepoPositions(
    input: z.infer<typeof GetReverseRepoPositionsInputSchema>,
    _context: Context,
  ): Promise<GetReverseRepoPositionsResult> {
    return this.query.run(input as never);
  }
}
