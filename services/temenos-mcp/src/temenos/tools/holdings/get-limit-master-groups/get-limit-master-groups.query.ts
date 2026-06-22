import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetLimitMasterGroupsInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
});

export type GetLimitMasterGroupsInput = z.infer<typeof GetLimitMasterGroupsInputSchema>;

export const GetLimitMasterGroupsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetLimitMasterGroupsResult = z.infer<typeof GetLimitMasterGroupsOutputSchema>;

@Injectable()
export class GetLimitMasterGroupsQuery {
  private readonly logger = new Logger(GetLimitMasterGroupsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetLimitMasterGroupsInput): Promise<GetLimitMasterGroupsResult> {
    this.logger.debug({}, 'get_limit_master_groups: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/limits/customers/masterGroups', {
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
      this.metrics.recordToolDuration('get_limit_master_groups', result, start);
    }
  }
}
