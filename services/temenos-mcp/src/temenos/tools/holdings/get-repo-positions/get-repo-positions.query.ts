import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetRepoPositionsInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
  portfolioId: z.string().optional().describe("ID of the portfolio or security account"),
  depositoryId: z.string().optional().describe("ID of the securities depository"),
  instrumentId: z.string().optional().describe("Identifier of the instrument"),
  quantity: z.string().optional().describe("Nominal quantity"),
});

export type GetRepoPositionsInput = z.infer<typeof GetRepoPositionsInputSchema>;

export const GetRepoPositionsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetRepoPositionsResult = z.infer<typeof GetRepoPositionsOutputSchema>;

@Injectable()
export class GetRepoPositionsQuery {
  private readonly logger = new Logger(GetRepoPositionsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetRepoPositionsInput): Promise<GetRepoPositionsResult> {
    this.logger.debug({}, 'get_repo_positions: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/instruments/repurchaseAgreements/positions', {
        recordId: input.recordId,
        portfolioId: input.portfolioId,
        depositoryId: input.depositoryId,
        instrumentId: input.instrumentId,
        quantity: input.quantity,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_repo_positions', result, start);
    }
  }
}
