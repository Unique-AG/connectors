import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetUsLoanCovenantsInputSchema, GetUsLoanCovenantsOutputSchema, GetUsLoanCovenantsQuery, type GetUsLoanCovenantsResult } from './get-us-loan-covenants.query';
import { META } from './get-us-loan-covenants-tool.meta';

@Injectable()
export class GetUsLoanCovenantsTool {
  public constructor(private readonly query: GetUsLoanCovenantsQuery) {}

  @Tool({
    name: 'get_us_loan_covenants',
    title: 'Get US Loan Covenants',
    description: 'Retrieve US model bank loan covenant definitions from Temenos.',
    parameters: GetUsLoanCovenantsInputSchema,
    outputSchema: GetUsLoanCovenantsOutputSchema,
    annotations: {
      title: 'Get US Loan Covenants',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsLoanCovenants(
    input: z.infer<typeof GetUsLoanCovenantsInputSchema>,
    _context: Context,
  ): Promise<GetUsLoanCovenantsResult> {
    return this.query.run(input as never);
  }
}
