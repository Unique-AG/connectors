import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetVostroAccountsInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
  customerId: z.string().optional().describe("Identifier of the customer"),
  productName: z.string().optional().describe("Product name of the bank for this account"),
  currencyId: z.string().optional().describe("ISO 4217 three-letter currency code"),
});

export type GetVostroAccountsInput = z.infer<typeof GetVostroAccountsInputSchema>;

export const GetVostroAccountsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetVostroAccountsResult = z.infer<typeof GetVostroAccountsOutputSchema>;

@Injectable()
export class GetVostroAccountsQuery {
  private readonly logger = new Logger(GetVostroAccountsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetVostroAccountsInput): Promise<GetVostroAccountsResult> {
    this.logger.debug({}, 'get_vostro_accounts: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/accounts/vostro/', {
        recordId: input.recordId,
        customerId: input.customerId,
        productName: input.productName,
        currencyId: input.currencyId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_vostro_accounts', result, start);
    }
  }
}
