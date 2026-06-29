import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetVostroAccountsInputSchema,
  GetVostroAccountsOutputSchema,
  GetVostroAccountsQuery,
  type GetVostroAccountsResult,
} from './get-vostro-accounts.query';
import { META } from './get-vostro-accounts-tool.meta';

@Injectable()
export class GetVostroAccountsTool {
  public constructor(private readonly query: GetVostroAccountsQuery) {}

  @Tool({
    name: 'get_vostro_accounts',
    title: 'Get Vostro Accounts',
    description:
      'Retrieve Vostro accounts from Temenos. Filter by record, customer, product, or currency.',
    parameters: GetVostroAccountsInputSchema,
    outputSchema: GetVostroAccountsOutputSchema,
    annotations: {
      title: 'Get Vostro Accounts',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getVostroAccounts(
    input: z.infer<typeof GetVostroAccountsInputSchema>,
    _context: Context,
  ): Promise<GetVostroAccountsResult> {
    return this.query.run(input);
  }
}
