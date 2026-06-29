import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetReverseRepoPositionsInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
  portfolioId: z.string().optional().describe('ID of the portfolio or security account'),
  instrumentId: z.string().optional().describe('Identifier of the instrument'),
  depositoryId: z.string().optional().describe('ID of the securities depository'),
  quantity: z.string().optional().describe('Nominal quantity'),
});

export type GetReverseRepoPositionsInput = z.infer<typeof GetReverseRepoPositionsInputSchema>;

export const GetReverseRepoPositionsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetReverseRepoPositionsResult = z.infer<typeof GetReverseRepoPositionsOutputSchema>;

@Injectable()
export class GetReverseRepoPositionsQuery {
  private readonly logger = new Logger(GetReverseRepoPositionsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetReverseRepoPositionsInput): Promise<GetReverseRepoPositionsResult> {
    this.logger.debug({}, 'get_reverse_repo_positions: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>(
        '/holdings/instruments/reverseRepurchaseAgreements/positions',
        {
          recordId: input.recordId,
          portfolioId: input.portfolioId,
          instrumentId: input.instrumentId,
          depositoryId: input.depositoryId,
          quantity: input.quantity,
        },
      );
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_reverse_repo_positions', result, start);
    }
  }
}
