import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetChequeTypesInputSchema = z.object({
  productName: z.string().optional().describe("Product name of the bank for this account"),
});

export type GetChequeTypesInput = z.infer<typeof GetChequeTypesInputSchema>;

export const GetChequeTypesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetChequeTypesResult = z.infer<typeof GetChequeTypesOutputSchema>;

@Injectable()
export class GetChequeTypesQuery {
  private readonly logger = new Logger(GetChequeTypesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetChequeTypesInput): Promise<GetChequeTypesResult> {
    this.logger.debug({}, 'get_cheque_types: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/chequeTypes', {
        productName: input.productName,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_cheque_types', result, start);
    }
  }
}
