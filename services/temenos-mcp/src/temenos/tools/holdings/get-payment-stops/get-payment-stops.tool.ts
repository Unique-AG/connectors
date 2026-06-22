import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetPaymentStopsInputSchema,
  GetPaymentStopsOutputSchema,
  GetPaymentStopsQuery,
  type GetPaymentStopsResult,
} from './get-payment-stops.query';
import { META } from './get-payment-stops-tool.meta';

@Injectable()
export class GetPaymentStopsTool {
  public constructor(private readonly query: GetPaymentStopsQuery) {}

  @Tool({
    name: 'get_payment_stops',
    title: 'Get Payment Stops',
    description:
      'Retrieve payment stop instructions from Temenos. Filter by record, customer, or stop type.',
    parameters: GetPaymentStopsInputSchema,
    outputSchema: GetPaymentStopsOutputSchema,
    annotations: {
      title: 'Get Payment Stops',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getPaymentStops(
    input: z.infer<typeof GetPaymentStopsInputSchema>,
    _context: Context,
  ): Promise<GetPaymentStopsResult> {
    return this.query.run(input as never);
  }
}
