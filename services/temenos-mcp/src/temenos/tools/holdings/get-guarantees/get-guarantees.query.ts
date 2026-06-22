import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetGuaranteesInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
  customerId: z.string().optional().describe('Identifier of the customer'),
  eventStatus: z
    .string()
    .optional()
    .describe('Request status: With Bank, With Customer, Approved, or Rejected'),
});

export type GetGuaranteesInput = z.infer<typeof GetGuaranteesInputSchema>;

export const GetGuaranteesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetGuaranteesResult = z.infer<typeof GetGuaranteesOutputSchema>;

@Injectable()
export class GetGuaranteesQuery {
  private readonly logger = new Logger(GetGuaranteesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetGuaranteesInput): Promise<GetGuaranteesResult> {
    this.logger.debug({}, 'get_guarantees: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/guarantees/requests', {
        recordId: input.recordId,
        customerId: input.customerId,
        eventStatus: input.eventStatus,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_guarantees', result, start);
    }
  }
}
