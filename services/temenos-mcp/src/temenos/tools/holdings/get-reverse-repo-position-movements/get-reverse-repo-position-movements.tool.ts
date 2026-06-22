import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetReverseRepoPositionMovementsInputSchema,
  GetReverseRepoPositionMovementsOutputSchema,
  GetReverseRepoPositionMovementsQuery,
  type GetReverseRepoPositionMovementsResult,
} from './get-reverse-repo-position-movements.query';
import { META } from './get-reverse-repo-position-movements-tool.meta';

@Injectable()
export class GetReverseRepoPositionMovementsTool {
  public constructor(private readonly query: GetReverseRepoPositionMovementsQuery) {}

  @Tool({
    name: 'get_reverse_repo_position_movements',
    title: 'Get Reverse Repo Position Movements',
    description: 'Retrieve reverse repurchase agreement position movements from Temenos.',
    parameters: GetReverseRepoPositionMovementsInputSchema,
    outputSchema: GetReverseRepoPositionMovementsOutputSchema,
    annotations: {
      title: 'Get Reverse Repo Position Movements',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getReverseRepoPositionMovements(
    input: z.infer<typeof GetReverseRepoPositionMovementsInputSchema>,
    _context: Context,
  ): Promise<GetReverseRepoPositionMovementsResult> {
    return this.query.run(input as never);
  }
}
