import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetPaymentFeesInputSchema,
  GetPaymentFeesOutputSchema,
  GetPaymentFeesQuery,
  type GetPaymentFeesResult,
} from './get-payment-fees.query';
import { META } from './get-payment-fees-tool.meta';

@Injectable()
export class GetPaymentFeesTool {
  public constructor(private readonly query: GetPaymentFeesQuery) {}

  @Tool({
    name: 'get_payment_fees',
    title: 'Get Payment Fees',
    description: 'Retrieve payment fee information from Temenos.',
    parameters: GetPaymentFeesInputSchema,
    outputSchema: GetPaymentFeesOutputSchema,
    annotations: {
      title: 'Get Payment Fees',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getPaymentFees(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetPaymentFeesResult> {
    return this.query.run(input);
  }
}
