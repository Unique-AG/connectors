import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetDerivativeOptionExpiresInputSchema,
  GetDerivativeOptionExpiresOutputSchema,
  GetDerivativeOptionExpiresQuery,
  type GetDerivativeOptionExpiresResult,
} from './get-derivative-option-expires.query';
import { META } from './get-derivative-option-expires-tool.meta';

@Injectable()
export class GetDerivativeOptionExpiresTool {
  public constructor(private readonly query: GetDerivativeOptionExpiresQuery) {}

  @Tool({
    name: 'get_derivative_option_expires',
    title: 'Get Derivative Option Expirations',
    description: 'Retrieve derivative option expiration operations from Temenos.',
    parameters: GetDerivativeOptionExpiresInputSchema,
    outputSchema: GetDerivativeOptionExpiresOutputSchema,
    annotations: {
      title: 'Get Derivative Option Expirations',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getDerivativeOptionExpires(
    input: z.infer<typeof GetDerivativeOptionExpiresInputSchema>,
    _context: Context,
  ): Promise<GetDerivativeOptionExpiresResult> {
    return this.query.run(input as never);
  }
}
