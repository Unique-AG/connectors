import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetRepoPositionsInputSchema, GetRepoPositionsOutputSchema, GetRepoPositionsQuery, type GetRepoPositionsResult } from './get-repo-positions.query';
import { META } from './get-repo-positions-tool.meta';

@Injectable()
export class GetRepoPositionsTool {
  public constructor(private readonly query: GetRepoPositionsQuery) {}

  @Tool({
    name: 'get_repo_positions',
    title: 'Get Repo Positions',
    description: 'Retrieve repurchase agreement current positions from Temenos.',
    parameters: GetRepoPositionsInputSchema,
    outputSchema: GetRepoPositionsOutputSchema,
    annotations: {
      title: 'Get Repo Positions',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getRepoPositions(
    input: z.infer<typeof GetRepoPositionsInputSchema>,
    _context: Context,
  ): Promise<GetRepoPositionsResult> {
    return this.query.run(input as never);
  }
}
