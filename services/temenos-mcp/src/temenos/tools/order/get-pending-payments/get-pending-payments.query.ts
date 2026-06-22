import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetPendingPaymentsInputSchema = z.object({
  company: z.string().optional().describe("The company code"),
  date: z.string().optional().describe("The date on which activity was performed"),
  transactionReference: z.string().optional().describe("Identifier for the transaction in the core system"),
  direction: z.string().optional().describe("Direction of the direct debit claim: Outward or Inward"),
  currency: z.string().optional().describe("ISO currency code"),
  amount: z.string().optional().describe("Payment amount"),
  debitClientID: z.string().optional().describe("Debit customer client ID"),
  creditClientID: z.string().optional().describe("Credit customer client ID"),
  debitMainAccountCurrencyCode: z.string().optional().describe("ISO currency code for the debit main account"),
  debitAccountId: z.string().optional().describe("Debit account number of the payment"),
  creditAccountId: z.string().optional().describe("Credit account identifier of the payment"),
});

export type GetPendingPaymentsInput = z.infer<typeof GetPendingPaymentsInputSchema>;

export const GetPendingPaymentsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetPendingPaymentsResult = z.infer<typeof GetPendingPaymentsOutputSchema>;

@Injectable()
export class GetPendingPaymentsQuery {
  private readonly logger = new Logger(GetPendingPaymentsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetPendingPaymentsInput): Promise<GetPendingPaymentsResult> {
    this.logger.debug({}, 'get_pending_payments: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/order/payments/pendingOrders', {
        company: input.company,
        date: input.date,
        transactionReference: input.transactionReference,
        direction: input.direction,
        currency: input.currency,
        amount: input.amount,
        debitClientID: input.debitClientID,
        creditClientID: input.creditClientID,
        debitMainAccountCurrencyCode: input.debitMainAccountCurrencyCode,
        debitAccountId: input.debitAccountId,
        creditAccountId: input.creditAccountId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_pending_payments', result, start);
    }
  }
}
