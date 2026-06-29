import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetUsIndustriesInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
});

export type GetUsIndustriesInput = z.infer<typeof GetUsIndustriesInputSchema>;

export const GetUsIndustriesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetUsIndustriesResult = z.infer<typeof GetUsIndustriesOutputSchema>;

@Injectable()
export class GetUsIndustriesQuery {
  private readonly logger = new Logger(GetUsIndustriesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetUsIndustriesInput): Promise<GetUsIndustriesResult> {
    this.logger.debug({}, 'get_us_industries: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/us/industries', {
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
      this.metrics.recordToolDuration('get_us_industries', result, start);
    }
  }
}
