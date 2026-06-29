import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetInterestConditionsInputSchema,
  GetInterestConditionsOutputSchema,
  GetInterestConditionsQuery,
  type GetInterestConditionsResult,
} from './get-interest-conditions.query';
import { META } from './get-interest-conditions-tool.meta';

@Injectable()
export class GetInterestConditionsTool {
  public constructor(private readonly query: GetInterestConditionsQuery) {}

  @Tool({
    name: 'get_interest_conditions',
    title: 'Get Interest Conditions',
    description: 'Retrieve product interest condition definitions from Temenos.',
    parameters: GetInterestConditionsInputSchema,
    outputSchema: GetInterestConditionsOutputSchema,
    annotations: {
      title: 'Get Interest Conditions',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getInterestConditions(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetInterestConditionsResult> {
    return this.query.run(input);
  }
}
