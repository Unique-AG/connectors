import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosRecordsOutputSchema, toTitledRecords } from '../../../titled-records';

export const GetLanguageCodesInputSchema = z.object({});

export type GetLanguageCodesInput = z.infer<typeof GetLanguageCodesInputSchema>;

export const GetLanguageCodesOutputSchema = TemenosRecordsOutputSchema;

export type GetLanguageCodesResult = z.infer<typeof GetLanguageCodesOutputSchema>;

@Injectable()
export class GetLanguageCodesQuery {
  private readonly logger = new Logger(GetLanguageCodesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetLanguageCodesResult> {
    this.logger.debug({}, 'get_language_codes: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>('/reference/languages/', undefined);
      return { success: true, ...toTitledRecords(response, 'Language') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_language_codes', result, start);
    }
  }
}
