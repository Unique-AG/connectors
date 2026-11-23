import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosHeaderSchema, TitledRecordsSchema, toTitledRecords } from '../../../titled-records';

export const GetCountriesInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetCountriesInput = z.infer<typeof GetCountriesInputSchema>;

export const GetCountriesOutputSchema = z
  .object({
    success: z.boolean(),
    data: TitledRecordsSchema.optional(),
    header: TemenosHeaderSchema.optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetCountriesResult = z.infer<typeof GetCountriesOutputSchema>;

@Injectable()
export class GetCountriesQuery {
  private readonly logger = new Logger(GetCountriesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetCountriesInput): Promise<GetCountriesResult> {
    this.logger.debug({}, 'get_countries: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>('/reference/countries', {
        recordId: input.recordId,
      });
      return { success: true, ...toTitledRecords(response, 'Country') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_countries', result, start);
    }
  }
}
