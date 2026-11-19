import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosRecordsOutputSchema, toTitledRecords } from '../../../titled-records';

export const GetUsLoanCovenantsInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetUsLoanCovenantsInput = z.infer<typeof GetUsLoanCovenantsInputSchema>;

export const GetUsLoanCovenantsOutputSchema = TemenosRecordsOutputSchema;

export type GetUsLoanCovenantsResult = z.infer<typeof GetUsLoanCovenantsOutputSchema>;

@Injectable()
export class GetUsLoanCovenantsQuery {
  private readonly logger = new Logger(GetUsLoanCovenantsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetUsLoanCovenantsInput): Promise<GetUsLoanCovenantsResult> {
    this.logger.debug({}, 'get_us_loan_covenants: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>('/reference/us/covenants', {
        recordId: input.recordId,
      });
      return { success: true, ...toTitledRecords(response, 'Loan covenant') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_us_loan_covenants', result, start);
    }
  }
}
