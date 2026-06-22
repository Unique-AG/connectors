import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetCategoriesInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
});

export type GetCategoriesInput = z.infer<typeof GetCategoriesInputSchema>;

export const GetCategoriesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetCategoriesResult = z.infer<typeof GetCategoriesOutputSchema>;

@Injectable()
export class GetCategoriesQuery {
  private readonly logger = new Logger(GetCategoriesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetCategoriesInput): Promise<GetCategoriesResult> {
    this.logger.debug({}, 'get_categories: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/categories', {
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
      this.metrics.recordToolDuration('get_categories', result, start);
    }
  }
}
