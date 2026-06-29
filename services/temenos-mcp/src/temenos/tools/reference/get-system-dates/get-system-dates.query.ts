import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetSystemDatesInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
  nextWorkingDate: z.string().optional().describe('Date of the next business day to be processed'),
  lastWorkingDate: z.string().optional().describe('Date of the last business day processed'),
});

export type GetSystemDatesInput = z.infer<typeof GetSystemDatesInputSchema>;

export const GetSystemDatesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetSystemDatesResult = z.infer<typeof GetSystemDatesOutputSchema>;

@Injectable()
export class GetSystemDatesQuery {
  private readonly logger = new Logger(GetSystemDatesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetSystemDatesInput): Promise<GetSystemDatesResult> {
    this.logger.debug({}, 'get_system_dates: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/dates', {
        recordId: input.recordId,
        nextWorkingDate: input.nextWorkingDate,
        lastWorkingDate: input.lastWorkingDate,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_system_dates', result, start);
    }
  }
}
