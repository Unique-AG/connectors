import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetPendingPaymentsInputSchema,
  GetPendingPaymentsOutputSchema,
  GetPendingPaymentsQuery,
  type GetPendingPaymentsResult,
} from './get-pending-payments.query';
import { META } from './get-pending-payments-tool.meta';

@Injectable()
export class GetPendingPaymentsTool {
  public constructor(private readonly query: GetPendingPaymentsQuery) {}

  @Tool({
    name: 'get_pending_payments',
    title: 'Get Pending Payments',
    description:
      'Retrieve pending payment orders from Temenos. Filter by company, date, transaction reference, currency, amount, or account IDs.',
    parameters: GetPendingPaymentsInputSchema,
    outputSchema: GetPendingPaymentsOutputSchema,
    annotations: {
      title: 'Get Pending Payments',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getPendingPayments(
    input: z.infer<typeof GetPendingPaymentsInputSchema>,
    _context: Context,
  ): Promise<GetPendingPaymentsResult> {
    return this.query.run(input);
  }
}
