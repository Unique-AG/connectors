import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetDerivativeOptionAssignsInputSchema, GetDerivativeOptionAssignsOutputSchema, GetDerivativeOptionAssignsQuery, type GetDerivativeOptionAssignsResult } from './get-derivative-option-assigns.query';
import { META } from './get-derivative-option-assigns-tool.meta';

@Injectable()
export class GetDerivativeOptionAssignsTool {
  public constructor(private readonly query: GetDerivativeOptionAssignsQuery) {}

  @Tool({
    name: 'get_derivative_option_assigns',
    title: 'Get Derivative Option Assignments',
    description: 'Retrieve derivative option assignment operations from Temenos.',
    parameters: GetDerivativeOptionAssignsInputSchema,
    outputSchema: GetDerivativeOptionAssignsOutputSchema,
    annotations: {
      title: 'Get Derivative Option Assignments',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getDerivativeOptionAssigns(
    input: z.infer<typeof GetDerivativeOptionAssignsInputSchema>,
    _context: Context,
  ): Promise<GetDerivativeOptionAssignsResult> {
    return this.query.run(input as never);
  }
}
