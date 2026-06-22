import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetAccountOfficersInputSchema,
  GetAccountOfficersOutputSchema,
  GetAccountOfficersQuery,
  type GetAccountOfficersResult,
} from './get-account-officers.query';
import { META } from './get-account-officers-tool.meta';

@Injectable()
export class GetAccountOfficersTool {
  public constructor(private readonly query: GetAccountOfficersQuery) {}

  @Tool({
    name: 'get_account_officers',
    title: 'Get Account Officers',
    description: 'Retrieve the list of account officers from Temenos.',
    parameters: GetAccountOfficersInputSchema,
    outputSchema: GetAccountOfficersOutputSchema,
    annotations: {
      title: 'Get Account Officers',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getAccountOfficers(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetAccountOfficersResult> {
    return this.query.run(input as never);
  }
}
