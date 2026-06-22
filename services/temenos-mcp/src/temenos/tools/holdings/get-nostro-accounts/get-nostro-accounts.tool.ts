import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetNostroAccountsInputSchema, GetNostroAccountsOutputSchema, GetNostroAccountsQuery, type GetNostroAccountsResult } from './get-nostro-accounts.query';
import { META } from './get-nostro-accounts-tool.meta';

@Injectable()
export class GetNostroAccountsTool {
  public constructor(private readonly query: GetNostroAccountsQuery) {}

  @Tool({
    name: 'get_nostro_accounts',
    title: 'Get Nostro Accounts',
    description: 'Retrieve the list of Nostro accounts from Temenos.',
    parameters: GetNostroAccountsInputSchema,
    outputSchema: GetNostroAccountsOutputSchema,
    annotations: {
      title: 'Get Nostro Accounts',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getNostroAccounts(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetNostroAccountsResult> {
    return this.query.run(input as never);
  }
}
