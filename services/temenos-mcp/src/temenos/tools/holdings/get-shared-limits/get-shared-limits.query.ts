import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosHeaderSchema, TitledRecordsSchema, toTitledRecords } from '../../../titled-records';

export const GetSharedLimitsInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetSharedLimitsInput = z.infer<typeof GetSharedLimitsInputSchema>;

export const GetSharedLimitsOutputSchema = z
  .object({
    success: z.boolean(),
    data: TitledRecordsSchema.optional(),
    header: TemenosHeaderSchema.optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetSharedLimitsResult = z.infer<typeof GetSharedLimitsOutputSchema>;

@Injectable()
export class GetSharedLimitsQuery {
  private readonly logger = new Logger(GetSharedLimitsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetSharedLimitsInput): Promise<GetSharedLimitsResult> {
    this.logger.debug({}, 'get_shared_limits: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>('/holdings/limits/sharedLimits', {
        recordId: input.recordId,
      });
      return { success: true, ...toTitledRecords(response, 'Shared limit') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_shared_limits', result, start);
    }
  }
}
