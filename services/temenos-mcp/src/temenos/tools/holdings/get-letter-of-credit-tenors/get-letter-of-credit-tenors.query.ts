import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosRecordsOutputSchema, toTitledRecords } from '../../../titled-records';

export const GetLetterOfCreditTenorsInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetLetterOfCreditTenorsInput = z.infer<typeof GetLetterOfCreditTenorsInputSchema>;

export const GetLetterOfCreditTenorsOutputSchema = TemenosRecordsOutputSchema;

export type GetLetterOfCreditTenorsResult = z.infer<typeof GetLetterOfCreditTenorsOutputSchema>;

@Injectable()
export class GetLetterOfCreditTenorsQuery {
  private readonly logger = new Logger(GetLetterOfCreditTenorsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetLetterOfCreditTenorsInput): Promise<GetLetterOfCreditTenorsResult> {
    this.logger.debug({}, 'get_letter_of_credit_tenors: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>('/holdings/letterOfCredits/tenors', {
        recordId: input.recordId,
      });
      return { success: true, ...toTitledRecords(response, 'Letter of credit tenor') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_letter_of_credit_tenors', result, start);
    }
  }
}
