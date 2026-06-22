import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetRepoPositionMovementsInputSchema,
  GetRepoPositionMovementsOutputSchema,
  GetRepoPositionMovementsQuery,
  type GetRepoPositionMovementsResult,
} from './get-repo-position-movements.query';
import { META } from './get-repo-position-movements-tool.meta';

@Injectable()
export class GetRepoPositionMovementsTool {
  public constructor(private readonly query: GetRepoPositionMovementsQuery) {}

  @Tool({
    name: 'get_repo_position_movements',
    title: 'Get Repo Position Movements',
    description: 'Retrieve repurchase agreement position movements from Temenos.',
    parameters: GetRepoPositionMovementsInputSchema,
    outputSchema: GetRepoPositionMovementsOutputSchema,
    annotations: {
      title: 'Get Repo Position Movements',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getRepoPositionMovements(
    input: z.infer<typeof GetRepoPositionMovementsInputSchema>,
    _context: Context,
  ): Promise<GetRepoPositionMovementsResult> {
    return this.query.run(input as never);
  }
}
