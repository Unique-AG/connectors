import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetLetterOfCreditIncoTermsInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetLetterOfCreditIncoTermsInput = z.infer<typeof GetLetterOfCreditIncoTermsInputSchema>;

export const GetLetterOfCreditIncoTermsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetLetterOfCreditIncoTermsResult = z.infer<
  typeof GetLetterOfCreditIncoTermsOutputSchema
>;

@Injectable()
export class GetLetterOfCreditIncoTermsQuery {
  private readonly logger = new Logger(GetLetterOfCreditIncoTermsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(
    input: GetLetterOfCreditIncoTermsInput,
  ): Promise<GetLetterOfCreditIncoTermsResult> {
    this.logger.debug({}, 'get_letter_of_credit_inco_terms: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/letterOfCredits/incoTerms', {
        recordId: input.recordId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_letter_of_credit_inco_terms', result, start);
    }
  }
}
