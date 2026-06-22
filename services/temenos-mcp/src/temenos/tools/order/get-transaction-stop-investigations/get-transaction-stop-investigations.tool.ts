import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetTransactionStopInvestigationsInputSchema,
  GetTransactionStopInvestigationsOutputSchema,
  GetTransactionStopInvestigationsQuery,
  type GetTransactionStopInvestigationsResult,
} from './get-transaction-stop-investigations.query';
import { META } from './get-transaction-stop-investigations-tool.meta';

@Injectable()
export class GetTransactionStopInvestigationsTool {
  public constructor(private readonly query: GetTransactionStopInvestigationsQuery) {}

  @Tool({
    name: 'get_transaction_stop_investigations',
    title: 'Get Transaction Stop Investigations',
    description: 'Retrieve transaction stop investigation records from Temenos.',
    parameters: GetTransactionStopInvestigationsInputSchema,
    outputSchema: GetTransactionStopInvestigationsOutputSchema,
    annotations: {
      title: 'Get Transaction Stop Investigations',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getTransactionStopInvestigations(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetTransactionStopInvestigationsResult> {
    return this.query.run(input as never);
  }
}
